"""Tests for lean_rewrite.evaluator.

Integration tests that build real modules are skipped automatically when
lake or mathlib4 is absent. The happy-path test uses the same worktree for
both baseline and candidate (same build = no rewrite yet), which exercises
the evaluation loop without needing two separate worktrees.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from lean_rewrite.evaluator import (
    EvalResult,
    ModuleComparison,
    ModuleMetrics,
    _count_unfolds,
    _inject_profiler_option,
    _module_to_path,
    _parse_elaboration_times,
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


def test_count_unfolds_qualified_prefix() -> None:
    src = "unfold Nat.dist\nunfold Nat.dist; lia\n"
    assert _count_unfolds(src, "dist") == 2


def test_count_unfolds_qualified_no_partial_match() -> None:
    src = "unfold Nat.distance\nunfold Nat.dist_comm\n"
    assert _count_unfolds(src, "dist") == 0


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
# Unit tests for _parse_elaboration_times (no I/O)
# ---------------------------------------------------------------------------

# Fixture: real lake build stdout for a single freshly-compiled module
_LAKE_STDOUT_SINGLE = """\
ℹ [2/3] Built Test (200ms)
info: stderr:
cumulative profiling times:
\t.olean serialization 10.1ms
\tattribute application 0.0622ms
\telaboration 1.28ms
\tparsing 0.204ms
Build completed successfully (3 jobs).
"""

# Fixture: replayed module (cached) — no profiling block
_LAKE_STDOUT_REPLAYED = """\
✔ [65/65] Replayed Mathlib.Logic.Basic
Build completed successfully (65 jobs).
"""

# Fixture: two modules, one fresh, one replayed
_LAKE_STDOUT_MIXED = """\
✔ [1/3] Replayed Mathlib.Logic.Basic
ℹ [2/3] Built Mathlib.Data.Nat.Dist (350ms)
info: stderr:
cumulative profiling times:
\telaboration 45.2ms
\tparsing 1.1ms
Build completed successfully (3 jobs).
"""

# Fixture: elaboration time in seconds (not ms)
_LAKE_STDOUT_SECONDS = """\
ℹ [1/1] Built BigModule (12300ms)
info: stderr:
cumulative profiling times:
\telaboration 3.5s
Build completed successfully (1 jobs).
"""


def test_parse_elaboration_times_single_ms() -> None:
    result = _parse_elaboration_times(_LAKE_STDOUT_SINGLE)
    assert set(result.keys()) == {"Test"}
    assert abs(result["Test"] - 0.00128) < 1e-9


def test_parse_elaboration_times_replayed_returns_empty() -> None:
    result = _parse_elaboration_times(_LAKE_STDOUT_REPLAYED)
    assert result == {}


def test_parse_elaboration_times_mixed_only_built() -> None:
    result = _parse_elaboration_times(_LAKE_STDOUT_MIXED)
    assert "Mathlib.Logic.Basic" not in result
    assert "Mathlib.Data.Nat.Dist" in result
    assert abs(result["Mathlib.Data.Nat.Dist"] - 0.0452) < 1e-9


def test_parse_elaboration_times_seconds_unit() -> None:
    result = _parse_elaboration_times(_LAKE_STDOUT_SECONDS)
    assert abs(result["BigModule"] - 3.5) < 1e-9


def test_parse_elaboration_times_empty_stdout() -> None:
    assert _parse_elaboration_times("") == {}


def test_parse_elaboration_times_no_profiling_block() -> None:
    # Built line but no profiling data within 50 lines
    stdout = "ℹ [1/1] Built SomeModule (100ms)\nBuild completed successfully (1 jobs).\n"
    result = _parse_elaboration_times(stdout)
    assert result == {}


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


# ---------------------------------------------------------------------------
# Unit tests for _inject_profiler_option and inject_profiler parameter
# ---------------------------------------------------------------------------


def _fake_build_result(worktree: Path, module: str) -> "BuildResult":
    from lean_rewrite.runner import BuildResult
    return BuildResult(
        module=module,
        worktree=worktree,
        command=("lake", "build", module),
        returncode=0,
        stdout="",
        stderr="",
        wall_time_sec=1.0,
        timed_out=False,
    )


def test_inject_profiler_option_prepends_to_existing_file(tmp_path: Path) -> None:
    """_inject_profiler_option prepends 'set_option profiler true' to an existing file."""
    (tmp_path / "Foo").mkdir()
    lean_file = tmp_path / "Foo" / "Bar.lean"
    lean_file.write_text("def x := 1\n", encoding="utf-8")

    _inject_profiler_option(tmp_path, "Foo.Bar")

    content = lean_file.read_text(encoding="utf-8")
    assert content == "set_option profiler true\ndef x := 1\n"


def test_inject_profiler_option_nonexistent_file_is_silent(tmp_path: Path) -> None:
    """_inject_profiler_option does nothing when the module file does not exist."""
    _inject_profiler_option(tmp_path, "Foo.DoesNotExist")  # must not raise


def test_evaluate_inject_profiler_true_inserts_option(tmp_path: Path) -> None:
    """evaluate(inject_profiler=True) inserts profiler option in both worktree files."""
    bwt = tmp_path / "baseline"
    cwt = tmp_path / "candidate"
    original = "def x := 1\n"
    for wt in (bwt, cwt):
        (wt / "Foo").mkdir(parents=True)
        (wt / "Foo" / "Bar.lean").write_text(original, encoding="utf-8")

    captured: dict[str, str] = {}

    def mock_build(worktree, module, **kwargs):
        path = Path(worktree) / "Foo" / "Bar.lean"
        captured[str(worktree)] = path.read_text(encoding="utf-8")
        return _fake_build_result(Path(worktree), module)

    with patch("lean_rewrite.evaluator.run_lake_build", side_effect=mock_build):
        evaluate(bwt, cwt, ["Foo.Bar"], inject_profiler=True)

    assert len(captured) == 2
    for content in captured.values():
        assert content.startswith("set_option profiler true\n")


def test_evaluate_inject_profiler_false_leaves_files_unchanged(tmp_path: Path) -> None:
    """evaluate(inject_profiler=False) does not modify module files."""
    bwt = tmp_path / "baseline"
    cwt = tmp_path / "candidate"
    original = "def x := 1\n"
    for wt in (bwt, cwt):
        (wt / "Foo").mkdir(parents=True)
        (wt / "Foo" / "Bar.lean").write_text(original, encoding="utf-8")

    def mock_build(worktree, module, **kwargs):
        return _fake_build_result(Path(worktree), module)

    with patch("lean_rewrite.evaluator.run_lake_build", side_effect=mock_build):
        evaluate(bwt, cwt, ["Foo.Bar"], inject_profiler=False)

    for wt in (bwt, cwt):
        assert (wt / "Foo" / "Bar.lean").read_text(encoding="utf-8") == original
