"""Compare two mathlib worktrees (baseline vs. candidate rewrite) for downstream modules.

Metrics reported per module:
  (a) wall-clock build time difference (candidate − baseline)
  (b) elaboration time: parsed from ``lake build`` stdout when ``set_option
      profiler true`` is active in the source (stored in ``ModuleMetrics.
      elaboration_time_sec``; None when profiler output is absent)
  (c) whether both builds succeeded
  (d) static unfold count (occurrences of `unfold <def_name>` in source) and
      proof LOC difference — a coarse proxy for how the rewrite affects downstream files
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from lean_rewrite.runner import BuildResult, run_lake_build


@dataclass(frozen=True)
class ModuleMetrics:
    """Metrics for a single module build in one worktree."""

    module: str
    build: BuildResult
    unfold_count: int
    proof_loc: int
    elaboration_time_sec: float | None = None

    @property
    def wall_time_sec(self) -> float:
        return self.build.wall_time_sec


@dataclass(frozen=True)
class ModuleComparison:
    """Per-module comparison between baseline and candidate worktrees."""

    module: str
    baseline: ModuleMetrics
    candidate: ModuleMetrics

    @property
    def both_succeeded(self) -> bool:
        return self.baseline.build.success and self.candidate.build.success

    @property
    def wall_time_delta(self) -> float:
        """Candidate minus baseline wall time in seconds (negative = faster)."""
        return self.candidate.wall_time_sec - self.baseline.wall_time_sec

    @property
    def unfold_count_delta(self) -> int:
        """Candidate minus baseline static unfold count."""
        return self.candidate.unfold_count - self.baseline.unfold_count

    @property
    def proof_loc_delta(self) -> int:
        """Candidate minus baseline non-blank line count."""
        return self.candidate.proof_loc - self.baseline.proof_loc


@dataclass
class EvalResult:
    """Aggregate result of an evaluation run across all downstream modules."""

    baseline_worktree: Path
    candidate_worktree: Path
    def_name: str
    comparisons: list[ModuleComparison] = field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        return all(c.both_succeeded for c in self.comparisons)

    @property
    def total_wall_time_delta(self) -> float:
        """Sum of wall_time_delta for modules where both builds succeeded."""
        return sum(c.wall_time_delta for c in self.comparisons if c.both_succeeded)

    @property
    def total_unfold_count_delta(self) -> int:
        return sum(c.unfold_count_delta for c in self.comparisons)

    @property
    def total_unfold_count_baseline(self) -> int:
        """Total unfold occurrences of the target def in baseline downstream files."""
        return sum(c.baseline.unfold_count for c in self.comparisons)


def _parse_elaboration_times(stdout: str) -> dict[str, float]:
    """Parse per-module elaboration times from ``lake build`` stdout.

    When ``set_option profiler true`` is active in a Lean source, ``lake build``
    captures the profiler output and emits it under the ``info: stderr:`` block
    that follows a ``Built <module>`` line.  Example fragment::

        ℹ [2/3] Built Mathlib.Data.Nat.Dist (1234ms)
        info: stderr:
        cumulative profiling times:
            elaboration 45.2ms
            ...

    Returns a dict from module name (as passed to ``lake build``) to elaboration
    time in seconds.  Modules that were replayed from the cloud cache emit a
    ``Replayed`` line instead of ``Built`` and have no profiling block; they are
    absent from the returned dict.
    """
    result: dict[str, float] = {}
    lines = stdout.splitlines()
    for i, line in enumerate(lines):
        m = re.search(r"Built\s+(\S+)", line)
        if not m:
            continue
        module_name = m.group(1)
        # Search the next 50 lines for the elaboration entry
        for j in range(i + 1, min(i + 51, len(lines))):
            em = re.match(r"\s+elaboration\s+([\d.]+)(ms|s)\s*$", lines[j])
            if em:
                value = float(em.group(1))
                unit = em.group(2)
                result[module_name] = value / 1000.0 if unit == "ms" else value
                break
    return result


def _module_to_path(worktree: Path, module: str) -> Path:
    """'Mathlib.Logic.Basic' → '<worktree>/Mathlib/Logic/Basic.lean'."""
    parts = module.split(".")
    return worktree.joinpath(*parts).with_suffix(".lean")


def _count_unfolds(source: str, def_name: str) -> int:
    """Count `unfold <def_name>` tactic occurrences in Lean source text."""
    if not def_name:
        return 0
    pattern = rf"\bunfold\s+{re.escape(def_name)}\b"
    return len(re.findall(pattern, source))


def _proof_loc(source: str) -> int:
    """Count non-blank lines in source text."""
    return sum(1 for line in source.splitlines() if line.strip())


def _collect_metrics(
    worktree: Path,
    module: str,
    build: BuildResult,
    def_name: str,
) -> ModuleMetrics:
    src_path = _module_to_path(worktree, module)
    if src_path.exists():
        source = src_path.read_text(encoding="utf-8", errors="replace")
        unfold_count = _count_unfolds(source, def_name)
        loc = _proof_loc(source)
    else:
        unfold_count = 0
        loc = 0
    elab_times = _parse_elaboration_times(build.stdout)
    return ModuleMetrics(
        module=module,
        build=build,
        unfold_count=unfold_count,
        proof_loc=loc,
        elaboration_time_sec=elab_times.get(module),
    )


def evaluate(
    baseline_worktree: str | Path,
    candidate_worktree: str | Path,
    modules: Sequence[str],
    def_name: str = "",
    *,
    timeout: float | None = None,
    lake: str = "lake",
) -> EvalResult:
    """Compare baseline and candidate worktree builds for downstream modules.

    Parameters
    ----------
    baseline_worktree:
        Path to the unmodified mathlib working tree.
    candidate_worktree:
        Path to the modified mathlib working tree (candidate rewrite applied).
    modules:
        Lean module names to build in both worktrees.
    def_name:
        Name of the rewritten definition (used for static unfold counting).
    timeout:
        Per-module build timeout in seconds (None = unlimited).
    lake:
        ``lake`` binary name or absolute path.

    Returns
    -------
    EvalResult
        Structured per-module and aggregate comparison metrics.
    """
    bwt = Path(baseline_worktree)
    cwt = Path(candidate_worktree)

    comparisons: list[ModuleComparison] = []
    for module in modules:
        base_build = run_lake_build(bwt, module, timeout=timeout, lake=lake)
        cand_build = run_lake_build(cwt, module, timeout=timeout, lake=lake)
        comparisons.append(
            ModuleComparison(
                module=module,
                baseline=_collect_metrics(bwt, module, base_build, def_name),
                candidate=_collect_metrics(cwt, module, cand_build, def_name),
            )
        )

    return EvalResult(
        baseline_worktree=bwt,
        candidate_worktree=cwt,
        def_name=def_name,
        comparisons=comparisons,
    )
