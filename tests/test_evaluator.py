"""Tests for lean_rewrite.evaluator.

Integration tests that build real modules are skipped automatically when
lake or mathlib4 is absent. The happy-path test uses the same worktree for
both baseline and candidate (same build = no rewrite yet), which exercises
the evaluation loop without needing two separate worktrees.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from lean_rewrite.evaluator import (
    EvalResult,
    ModuleComparison,
    ModuleMetrics,
    _count_unfolds,
    _module_to_path,
    _proof_loc,
    evaluate,
)
from lean_rewrite.runner import BuildResult

MATHLIB = Path("/Users/san/mathlib4")
_HAS_LAKE = shutil.which("lake") is not None
_HAS_MATHLIB = MATHLIB.is_dir()

requires_lean = pytest.mark.skipif(
    not (_HAS_LAKE and _HAS_MATHLIB),
    reason="requires lake on PATH and mathlib4 at /Users/san/mathlib4",
)


# ---------------------------------------------------------------------------
# Unit tests for static analysis helpers (no I/O)
# ---------------------------------------------------------------------------


def test_count_unfolds_basic() -> None:
    src = "  unfold myDef\n  simp\n  unfold myDef\n"
    assert _count_unfolds(src, "myDef") == 2


def test_count_unfolds_no_match() -> None:
    src = "unfold otherDef\n"
    assert _count_unfolds(src, "myDef") == 0


def test_count_unfolds_no_prefix_match() -> None:
    src = "unfold myDefExtra\n"
    assert _count_unfolds(src, "myDef") == 0


def test_count_unfolds_empty_def_name() -> None:
    src = "unfold something\n"
    assert _count_unfolds(src, "") == 0


def test_count_unfolds_with_trailing_args() -> None:
    # `unfold Foo Bar` — Foo should be counted, Bar not
    src = "unfold Foo Bar\n"
    assert _count_unfolds(src, "Foo") == 1
    assert _count_unfolds(src, "Bar") == 0  # \bBar\b not following `unfold`


def test_proof_loc_basic() -> None:
    src = "def foo := 1\n\n-- comment\n  \n"
    assert _proof_loc(src) == 2


def test_proof_loc_empty() -> None:
    assert _proof_loc("") == 0
    assert _proof_loc("\n\n  \n") == 0


def test_module_to_path() -> None:
    wt = Path("/some/mathlib")
    p = _module_to_path(wt, "Mathlib.Logic.Basic")
    assert p == Path("/some/mathlib/Mathlib/Logic/Basic.lean")


# ---------------------------------------------------------------------------
# Unit tests for dataclass properties (no I/O, synthetic BuildResult)
# ---------------------------------------------------------------------------


def _fake_build(success: bool, wall: float, module: str = "M") -> BuildResult:
    return BuildResult(
        module=module,
        worktree=Path("/fake"),
        command=("lake", "build", module),
        returncode=0 if success else 1,
        stdout="",
        stderr="",
        wall_time_sec=wall,
        timed_out=False,
    )


def _fake_metrics(success: bool, wall: float, unfolds: int = 0, loc: int = 0) -> ModuleMetrics:
    return ModuleMetrics(
        module="M",
        build=_fake_build(success, wall),
        unfold_count=unfolds,
        proof_loc=loc,
    )


def test_module_comparison_both_succeeded() -> None:
    cmp = ModuleComparison(
        module="M",
        baseline=_fake_metrics(True, 1.0),
        candidate=_fake_metrics(True, 0.8),
    )
    assert cmp.both_succeeded is True
    assert abs(cmp.wall_time_delta - (-0.2)) < 1e-9


def test_module_comparison_one_failed() -> None:
    cmp = ModuleComparison(
        module="M",
        baseline=_fake_metrics(True, 1.0),
        candidate=_fake_metrics(False, 2.0),
    )
    assert cmp.both_succeeded is False


def test_module_comparison_deltas() -> None:
    cmp = ModuleComparison(
        module="M",
        baseline=_fake_metrics(True, 1.0, unfolds=3, loc=100),
        candidate=_fake_metrics(True, 1.0, unfolds=1, loc=95),
    )
    assert cmp.unfold_count_delta == -2
    assert cmp.proof_loc_delta == -5


def test_eval_result_all_succeeded_true() -> None:
    cmp = ModuleComparison(
        module="M",
        baseline=_fake_metrics(True, 1.0),
        candidate=_fake_metrics(True, 0.9),
    )
    result = EvalResult(
        baseline_worktree=Path("/b"),
        candidate_worktree=Path("/c"),
        def_name="foo",
        comparisons=[cmp],
    )
    assert result.all_succeeded is True
    assert abs(result.total_wall_time_delta - (-0.1)) < 1e-9


def test_eval_result_all_succeeded_false() -> None:
    cmp = ModuleComparison(
        module="M",
        baseline=_fake_metrics(True, 1.0),
        candidate=_fake_metrics(False, 1.0),
    )
    result = EvalResult(
        baseline_worktree=Path("/b"),
        candidate_worktree=Path("/c"),
        def_name="foo",
        comparisons=[cmp],
    )
    assert result.all_succeeded is False
    # failed comparisons excluded from total_wall_time_delta
    assert result.total_wall_time_delta == 0.0


def test_eval_result_empty() -> None:
    result = EvalResult(
        baseline_worktree=Path("/b"),
        candidate_worktree=Path("/c"),
        def_name="",
    )
    assert result.all_succeeded is True
    assert result.total_wall_time_delta == 0.0
    assert result.total_unfold_count_delta == 0
    assert result.total_unfold_count_baseline == 0


def test_eval_result_total_unfold_count_baseline() -> None:
    """total_unfold_count_baseline sums baseline unfold_count across all modules."""
    cmp1 = ModuleComparison(
        module="A",
        baseline=_fake_metrics(True, 1.0, unfolds=10),
        candidate=_fake_metrics(True, 1.0, unfolds=10),  # delta=0, but baseline=10
    )
    cmp2 = ModuleComparison(
        module="B",
        baseline=_fake_metrics(True, 1.0, unfolds=6),
        candidate=_fake_metrics(True, 1.0, unfolds=6),
    )
    result = EvalResult(
        baseline_worktree=Path("/b"),
        candidate_worktree=Path("/c"),
        def_name="foo",
        comparisons=[cmp1, cmp2],
    )
    assert result.total_unfold_count_baseline == 16
    assert result.total_unfold_count_delta == 0


def test_eval_result_baseline_count_nat_dist_scenario() -> None:
    """Nat.dist scenario: 16 baseline unfolds, delta=0 → baseline=16."""
    cmp = ModuleComparison(
        module="Mathlib.Data.Nat.Dist",
        baseline=_fake_metrics(True, 15.0, unfolds=16),
        candidate=_fake_metrics(True, 15.0, unfolds=16),
    )
    result = EvalResult(
        baseline_worktree=Path("/mathlib"),
        candidate_worktree=Path("/cand"),
        def_name="dist",
        comparisons=[cmp],
    )
    assert result.total_unfold_count_baseline == 16
    assert result.all_succeeded is True


# ---------------------------------------------------------------------------
# Integration tests (require mathlib4 + lake)
# ---------------------------------------------------------------------------


@requires_lean
def test_evaluate_same_worktree_succeeds() -> None:
    """Using the same worktree for both sides: both builds succeed, delta ~0."""
    result = evaluate(
        MATHLIB,
        MATHLIB,
        ["Mathlib.Logic.Basic"],
        def_name="Xor'",
        timeout=120,
    )

    assert isinstance(result, EvalResult)
    assert len(result.comparisons) == 1
    cmp = result.comparisons[0]
    assert cmp.module == "Mathlib.Logic.Basic"
    assert cmp.both_succeeded, (
        f"build failed:\n  baseline rc={cmp.baseline.build.returncode}\n"
        f"  candidate rc={cmp.candidate.build.returncode}\n"
        f"  stderr: {cmp.baseline.build.stderr[:200]}"
    )
    assert result.all_succeeded
    # Same worktree → same source files → unfold delta is 0
    assert cmp.unfold_count_delta == 0
    assert cmp.proof_loc_delta == 0


@requires_lean
def test_evaluate_bad_module_not_succeeded() -> None:
    """A non-existent module name causes both_succeeded=False."""
    result = evaluate(
        MATHLIB,
        MATHLIB,
        ["Mathlib.ThisModuleDoesNotExist_T005_test"],
        timeout=60,
    )
    assert len(result.comparisons) == 1
    assert result.comparisons[0].both_succeeded is False
    assert result.all_succeeded is False
