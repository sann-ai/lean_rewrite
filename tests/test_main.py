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


def test_no_improvement_when_zero_baseline_and_no_delta():
    # baseline=0 unfolds and delta=0 → no signal → rejected
    result = _eval_result([_comparison(base_unfold=0, cand_unfold=0)])
    assert is_improvement(result) is False


def test_no_improvement_when_zero_baseline_unfold_increases():
    # baseline=0, candidate added unfolds — also no improvement
    result = _eval_result([_comparison(base_unfold=0, cand_unfold=5)])
    assert is_improvement(result) is False


def test_improvement_when_baseline_has_unfolds_even_without_delta():
    # baseline=16 unfolds, candidate unchanged → abbrev makes them no-ops → ACCEPTED
    result = _eval_result([_comparison(base_unfold=16, cand_unfold=16)])
    assert is_improvement(result) is True


def test_improvement_nat_dist_scenario():
    # Nat.dist scenario: 16 baseline unfolds, delta=0 (no source changes to downstream)
    comparisons = [_comparison("Mathlib.Data.Nat.Dist", base_unfold=16, cand_unfold=16)]
    result = _eval_result(comparisons, def_name="dist")
    assert is_improvement(result) is True


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


def test_improvement_when_instance_context_baseline_positive():
    """SkewPolynomial scenario: no unfolds but typeclass synthesis context exists."""
    build = _ok_build()
    base_m = ModuleMetrics(module="M", build=build, unfold_count=0, proof_loc=10, instance_context_count=1)
    cand_m = ModuleMetrics(module="M", build=build, unfold_count=0, proof_loc=10, instance_context_count=1)
    cmp = ModuleComparison(module="M", baseline=base_m, candidate=cand_m)
    result = _eval_result([cmp], def_name="SkewPolynomial")
    assert is_improvement(result) is True


def test_no_improvement_when_all_signals_zero():
    """All signals absent — all-zero metrics → REJECTED."""
    build = _ok_build()
    base_m = ModuleMetrics(module="M", build=build, unfold_count=0, proof_loc=10, instance_context_count=0)
    cand_m = ModuleMetrics(module="M", build=build, unfold_count=0, proof_loc=10, instance_context_count=0)
    cmp = ModuleComparison(module="M", baseline=base_m, candidate=cand_m)
    result = _eval_result([cmp], def_name="foo")
    assert is_improvement(result) is False


def test_improvement_skew_polynomial_scenario():
    """Mocked SkewPolynomial case: baseline has 3 instance-context lines, no unfolds."""
    build = _ok_build()
    base_m = ModuleMetrics(module="Mathlib.RingTheory.SkewPolynomial.Basic", build=build,
                           unfold_count=0, proof_loc=500, instance_context_count=3)
    cand_m = ModuleMetrics(module="Mathlib.RingTheory.SkewPolynomial.Basic", build=build,
                           unfold_count=0, proof_loc=500, instance_context_count=3)
    cmp = ModuleComparison(module="Mathlib.RingTheory.SkewPolynomial.Basic",
                           baseline=base_m, candidate=cand_m)
    result = _eval_result([cmp], def_name="SkewPolynomial")
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
    result = _eval_result([_comparison(base_unfold=0, cand_unfold=0)])
    report = format_report(result, improved=False)
    assert "REJECTED" in report
    assert "unfold" in report.lower()


def test_format_report_includes_baseline_unfold_count():
    result = _eval_result([_comparison(base_unfold=16, cand_unfold=16)])
    report = format_report(result, improved=True)
    assert "Baseline unfold count:  16" in report


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
    # zero baseline unfolds and no delta → rejected
    mock_eval.return_value = _eval_result([_comparison(base_unfold=0, cand_unfold=0)])
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


@patch("lean_rewrite.main._git_worktree_remove")
@patch("lean_rewrite.main._git_worktree_add")
@patch("lean_rewrite.main.evaluate")
def test_run_pipeline_remove_unfolds_modifies_downstream(mock_eval, mock_add, mock_remove, tmp_path):
    lean_file = tmp_path / "Foo.lean"
    lean_file.write_text("def foo := 1\n")

    ds_rel = "Mathlib/Bar.lean"
    ds_with_unfolds = "theorem bar : True := by\n  unfold foo\n  trivial\n"

    def _side_effect_add(mathlib, dest):
        (dest / "Foo.lean").parent.mkdir(parents=True, exist_ok=True)
        (dest / "Foo.lean").write_text("")
        (dest / ds_rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / ds_rel).write_text(ds_with_unfolds)

    mock_add.side_effect = _side_effect_add

    seen_ds_content = []

    def _capture_eval(*, candidate_worktree, **kw):
        ds_path = candidate_worktree / ds_rel
        if ds_path.exists():
            seen_ds_content.append(ds_path.read_text())
        return _eval_result([_comparison(base_unfold=1, cand_unfold=0)])

    mock_eval.side_effect = _capture_eval

    rc = run_pipeline(
        mathlib=tmp_path,
        target_file="Foo.lean",
        def_name="foo",
        downstream=["Mathlib.Bar"],
        remove_unfolds=True,
    )

    assert rc == 0
    assert seen_ds_content, "evaluate was never called"
    assert "unfold foo" not in seen_ds_content[0]
    assert "trivial" in seen_ds_content[0]


@patch("lean_rewrite.main._git_worktree_remove")
@patch("lean_rewrite.main._git_worktree_add")
@patch("lean_rewrite.main.evaluate")
def test_run_pipeline_without_remove_unfolds_leaves_downstream(mock_eval, mock_add, mock_remove, tmp_path):
    lean_file = tmp_path / "Foo.lean"
    lean_file.write_text("def foo := 1\n")

    ds_rel = "Mathlib/Bar.lean"
    ds_with_unfolds = "theorem bar : True := by\n  unfold foo\n  trivial\n"

    def _side_effect_add(mathlib, dest):
        (dest / "Foo.lean").parent.mkdir(parents=True, exist_ok=True)
        (dest / "Foo.lean").write_text("")
        (dest / ds_rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / ds_rel).write_text(ds_with_unfolds)

    mock_add.side_effect = _side_effect_add

    seen_ds_content = []

    def _capture_eval(*, candidate_worktree, **kw):
        ds_path = candidate_worktree / ds_rel
        if ds_path.exists():
            seen_ds_content.append(ds_path.read_text())
        return _eval_result([_comparison(base_unfold=1, cand_unfold=1)])

    mock_eval.side_effect = _capture_eval

    run_pipeline(
        mathlib=tmp_path,
        target_file="Foo.lean",
        def_name="foo",
        downstream=["Mathlib.Bar"],
        remove_unfolds=False,
    )

    assert seen_ds_content, "evaluate was never called"
    assert "unfold foo" in seen_ds_content[0]


# ---------------------------------------------------------------------------
# SKIPPED_TERMINATION_BY path
# ---------------------------------------------------------------------------

def test_run_pipeline_skips_termination_by(tmp_path: Path) -> None:
    # A def with termination_by should produce SKIPPED_TERMINATION_BY verdict
    lean_file = tmp_path / "Foo.lean"
    lean_file.write_text(
        "def reverseRecOn (n : Nat) : Nat := n\n"
        "termination_by n\n"
    )
    result = run_pipeline(
        mathlib=tmp_path,
        target_file="Foo.lean",
        def_name="reverseRecOn",
        downstream=["Foo"],
    )
    assert result == 1


def test_run_pipeline_skips_termination_by_writes_report(tmp_path: Path) -> None:
    lean_file = tmp_path / "Foo.lean"
    lean_file.write_text(
        "def reverseRecOn (n : Nat) : Nat := n\n"
        "termination_by n\n"
    )
    out_dir = tmp_path / "out"
    run_pipeline(
        mathlib=tmp_path,
        target_file="Foo.lean",
        def_name="reverseRecOn",
        downstream=["Foo"],
        output_dir=out_dir,
    )
    report = (out_dir / "report.txt").read_text()
    assert "SKIPPED_TERMINATION_BY" in report
    assert not (out_dir / "candidate.patch").exists()


@patch("lean_rewrite.main._git_worktree_remove")
@patch("lean_rewrite.main._git_worktree_add")
@patch("lean_rewrite.main.evaluate")
def test_run_pipeline_no_skip_without_termination_by(mock_eval, mock_add, mock_remove, tmp_path: Path) -> None:
    # A def without termination_by should NOT be skipped — evaluate must be called
    lean_file = tmp_path / "Foo.lean"
    lean_file.write_text("def foo := 1\n")

    def _side_add(mathlib, dest):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "Foo.lean").write_text("")

    mock_add.side_effect = _side_add

    from lean_rewrite.evaluator import EvalResult, ModuleComparison, ModuleMetrics
    from lean_rewrite.runner import BuildResult

    def _make_br(success: bool) -> BuildResult:
        return BuildResult(
            module="Foo",
            worktree=str(tmp_path),
            command=["lake", "build", "Foo"],
            returncode=0 if success else 1,
            stdout="",
            stderr="",
            wall_time_sec=1.0,
            timed_out=False,
        )

    mock_eval.return_value = EvalResult(
        def_name="foo",
        baseline_worktree=str(tmp_path),
        candidate_worktree=str(tmp_path / "cand"),
        comparisons=[
            ModuleComparison(
                module="Foo",
                baseline=ModuleMetrics(module="Foo", build=_make_br(True), unfold_count=1, proof_loc=0),
                candidate=ModuleMetrics(module="Foo", build=_make_br(True), unfold_count=1, proof_loc=0),
            )
        ],
    )
    run_pipeline(
        mathlib=tmp_path,
        target_file="Foo.lean",
        def_name="foo",
        downstream=["Foo"],
    )
    mock_eval.assert_called_once()


# ---------------------------------------------------------------------------
# simp-attr transform tests
# ---------------------------------------------------------------------------

@patch("lean_rewrite.main._git_worktree_remove")
@patch("lean_rewrite.main._git_worktree_add")
@patch("lean_rewrite.main.evaluate")
@patch("lean_rewrite.main.add_simp_attr", return_value="@[simp]\ndef foo := 1\n")
def test_run_pipeline_simp_attr_applies_add_simp_attr(mock_simp, mock_eval, mock_add, mock_remove, tmp_path):
    lean_file = tmp_path / "Foo.lean"
    lean_file.write_text("def foo := 1\n")
    mock_add.side_effect = _make_worktree_side_effect("Foo.lean")
    mock_eval.return_value = _eval_result([_comparison(base_unfold=3, cand_unfold=0)])
    rc = run_pipeline(
        mathlib=tmp_path,
        target_file="Foo.lean",
        def_name="foo",
        downstream=["M"],
        transform="simp-attr",
    )
    assert rc == 0
    # add_simp_attr (not def_to_abbrev) was invoked for this def
    mock_simp.assert_called_once_with("def foo := 1\n", "foo")


def test_run_pipeline_simp_attr_does_not_skip_termination_by(tmp_path):
    # simp-attr should NOT skip defs with termination_by (guard is def-to-abbrev only)
    lean_file = tmp_path / "Foo.lean"
    lean_file.write_text(
        "def reverseRecOn (n : Nat) : Nat := n\n"
        "termination_by n\n"
    )
    # No worktree created → will fail at _git_worktree_add, but that's fine;
    # the key is it must NOT return 1 via the SKIPPED_TERMINATION_BY path.
    # We mock to avoid actual git calls.
    with patch("lean_rewrite.main._git_worktree_add"), \
         patch("lean_rewrite.main._git_worktree_remove"), \
         patch("lean_rewrite.main.evaluate") as mock_eval:
        wt_path = tmp_path / "cand"
        wt_path.mkdir()
        (wt_path / "Foo.lean").write_text("")

        def _side_add(mathlib, dest):
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "Foo.lean").write_text("")

        from lean_rewrite.main import _git_worktree_add
        import lean_rewrite.main as lrm
        lrm._git_worktree_add = _side_add
        mock_eval.return_value = _eval_result([_comparison(base_unfold=0, cand_unfold=0)])

        rc = run_pipeline(
            mathlib=tmp_path,
            target_file="Foo.lean",
            def_name="reverseRecOn",
            downstream=["M"],
            transform="simp-attr",
        )
        # Should not short-circuit with SKIPPED_TERMINATION_BY (rc would be 1 from that path);
        # evaluate was called, so short-circuit did not fire.
        mock_eval.assert_called_once()


def test_run_pipeline_simp_attr_noop_returns_1(tmp_path):
    # If the def already has @[simp], add_simp_attr is a no-op → rc=1
    lean_file = tmp_path / "Foo.lean"
    lean_file.write_text("@[simp]\ndef foo := 1\n")
    rc = run_pipeline(
        mathlib=tmp_path,
        target_file="Foo.lean",
        def_name="foo",
        downstream=["M"],
        transform="simp-attr",
    )
    assert rc == 1
