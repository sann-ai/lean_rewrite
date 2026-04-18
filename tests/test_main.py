"""Unit tests for lean_rewrite.main pipeline logic."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lean_rewrite.evaluator import EvalResult, ModuleComparison, ModuleMetrics
from lean_rewrite.main import (
    format_report,
    is_improvement,
    make_patch,
    run_pipeline,
)
from lean_rewrite.runner import BuildResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok_build(module: str = "M", worktree: str = "/wt") -> BuildResult:
    return BuildResult(
        module=module,
        worktree=Path(worktree),
        command=("lake", "build", module),
        returncode=0,
        stdout="",
        stderr="",
        wall_time_sec=1.0,
        timed_out=False,
    )


def _fail_build(module: str = "M", worktree: str = "/wt") -> BuildResult:
    return BuildResult(
        module=module,
        worktree=Path(worktree),
        command=("lake", "build", module),
        returncode=1,
        stdout="",
        stderr="error",
        wall_time_sec=0.5,
        timed_out=False,
    )


def _metrics(build: BuildResult, unfold: int = 0, loc: int = 10) -> ModuleMetrics:
    return ModuleMetrics(module=build.module, build=build, unfold_count=unfold, proof_loc=loc)


def _comparison(
    module: str = "M",
    base_unfold: int = 5,
    cand_unfold: int = 3,
    base_ok: bool = True,
    cand_ok: bool = True,
) -> ModuleComparison:
    base_build = _ok_build(module) if base_ok else _fail_build(module)
    cand_build = _ok_build(module) if cand_ok else _fail_build(module)
    return ModuleComparison(
        module=module,
        baseline=_metrics(base_build, unfold=base_unfold),
        candidate=_metrics(cand_build, unfold=cand_unfold),
    )


def _eval_result(
    comparisons: list[ModuleComparison],
    def_name: str = "dist",
) -> EvalResult:
    return EvalResult(
        baseline_worktree=Path("/mathlib"),
        candidate_worktree=Path("/cand"),
        def_name=def_name,
        comparisons=comparisons,
    )


# ---------------------------------------------------------------------------
# is_improvement
# ---------------------------------------------------------------------------

def test_improvement_when_unfolds_reduced():
    result = _eval_result([_comparison(base_unfold=5, cand_unfold=3)])
    assert is_improvement(result) is True


def test_no_improvement_when_no_unfold_reduction():
    result = _eval_result([_comparison(base_unfold=3, cand_unfold=3)])
    assert is_improvement(result) is False


def test_no_improvement_when_unfold_increases():
    result = _eval_result([_comparison(base_unfold=3, cand_unfold=5)])
    assert is_improvement(result) is False


def test_no_improvement_when_build_fails():
    result = _eval_result([_comparison(base_unfold=5, cand_unfold=0, cand_ok=False)])
    assert is_improvement(result) is False


def test_improvement_with_multiple_modules():
    comparisons = [
        _comparison("A", base_unfold=3, cand_unfold=0),
        _comparison("B", base_unfold=5, cand_unfold=2),
    ]
    result = _eval_result(comparisons)
    assert is_improvement(result) is True


# ---------------------------------------------------------------------------
# make_patch
# ---------------------------------------------------------------------------

def test_make_patch_produces_unified_diff():
    orig = "def foo := 1\n"
    cand = "abbrev foo := 1\n"
    patch = make_patch("Mathlib/Foo.lean", orig, cand)
    assert "--- a/Mathlib/Foo.lean" in patch
    assert "+++ b/Mathlib/Foo.lean" in patch
    assert "-def foo" in patch
    assert "+abbrev foo" in patch


def test_make_patch_empty_when_no_change():
    src = "abbrev foo := 1\n"
    patch = make_patch("Mathlib/Foo.lean", src, src)
    assert patch == ""


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------

def test_format_report_improved():
    result = _eval_result([_comparison(base_unfold=5, cand_unfold=2)])
    report = format_report(result, improved=True)
    assert "IMPROVED" in report
    assert "dist" in report


def test_format_report_rejected_build_fail():
    result = _eval_result([_comparison(cand_ok=False)])
    report = format_report(result, improved=False)
    assert "REJECTED" in report
    assert "failed" in report.lower()


def test_format_report_rejected_no_unfold_reduction():
    result = _eval_result([_comparison(base_unfold=3, cand_unfold=3)])
    report = format_report(result, improved=False)
    assert "REJECTED" in report
    assert "unfold" in report.lower()


# ---------------------------------------------------------------------------
# run_pipeline (mocked)
# ---------------------------------------------------------------------------

def test_run_pipeline_missing_file(tmp_path):
    rc = run_pipeline(
        mathlib=tmp_path,
        target_file="NonExistent.lean",
        def_name="foo",
        downstream=["M"],
    )
    assert rc == 2


def test_run_pipeline_def_not_found(tmp_path):
    lean_file = tmp_path / "Foo.lean"
    lean_file.write_text("def bar := 1\n")
    rc = run_pipeline(
        mathlib=tmp_path,
        target_file="Foo.lean",
        def_name="nonexistent",
        downstream=["M"],
    )
    assert rc == 2


def test_run_pipeline_no_change(tmp_path):
    lean_file = tmp_path / "Foo.lean"
    lean_file.write_text("abbrev foo := 1\n")
    rc = run_pipeline(
        mathlib=tmp_path,
        target_file="Foo.lean",
        def_name="foo",
        downstream=["M"],
    )
    # def_to_abbrev on an abbrev: DefNotFoundError → rc=2 (no top-level def)
    assert rc == 2


def _make_worktree_side_effect(target_file: str):
    """Return a side_effect for mock_add that creates the worktree dir structure."""
    def _side_effect(mathlib: "Path", dest: "Path") -> None:
        (dest / target_file).parent.mkdir(parents=True, exist_ok=True)
        (dest / target_file).write_text("")
    return _side_effect


@patch("lean_rewrite.main._git_worktree_remove")
@patch("lean_rewrite.main._git_worktree_add")
@patch("lean_rewrite.main.evaluate")
def test_run_pipeline_improvement(mock_eval, mock_add, mock_remove, tmp_path):
    lean_file = tmp_path / "Foo.lean"
    lean_file.write_text("def foo := 1\n")
    mock_add.side_effect = _make_worktree_side_effect("Foo.lean")
    mock_eval.return_value = _eval_result([_comparison(base_unfold=5, cand_unfold=0)])
    rc = run_pipeline(
        mathlib=tmp_path,
        target_file="Foo.lean",
        def_name="foo",
        downstream=["M"],
    )
    assert rc == 0
    mock_add.assert_called_once()
    mock_remove.assert_called_once()


@patch("lean_rewrite.main._git_worktree_remove")
@patch("lean_rewrite.main._git_worktree_add")
@patch("lean_rewrite.main.evaluate")
def test_run_pipeline_reject(mock_eval, mock_add, mock_remove, tmp_path):
    lean_file = tmp_path / "Foo.lean"
    lean_file.write_text("def foo := 1\n")
    mock_add.side_effect = _make_worktree_side_effect("Foo.lean")
    mock_eval.return_value = _eval_result([_comparison(base_unfold=3, cand_unfold=3)])
    rc = run_pipeline(
        mathlib=tmp_path,
        target_file="Foo.lean",
        def_name="foo",
        downstream=["M"],
    )
    assert rc == 1


@patch("lean_rewrite.main._git_worktree_remove")
@patch("lean_rewrite.main._git_worktree_add")
@patch("lean_rewrite.main.evaluate")
def test_run_pipeline_writes_output_dir(mock_eval, mock_add, mock_remove, tmp_path):
    lean_file = tmp_path / "Foo.lean"
    lean_file.write_text("def foo := 1\n")
    out_dir = tmp_path / "out"
    mock_add.side_effect = _make_worktree_side_effect("Foo.lean")
    mock_eval.return_value = _eval_result([_comparison(base_unfold=5, cand_unfold=0)])
    run_pipeline(
        mathlib=tmp_path,
        target_file="Foo.lean",
        def_name="foo",
        downstream=["M"],
        output_dir=out_dir,
    )
    assert (out_dir / "report.txt").exists()
    assert (out_dir / "candidate.patch").exists()
