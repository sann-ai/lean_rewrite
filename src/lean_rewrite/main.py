"""End-to-end lean_rewrite pipeline: def → abbrev transformation + evaluation.

Usage:
    python -m lean_rewrite.main \\
        --mathlib /path/to/mathlib4 \\
        --file Mathlib/Data/Nat/Dist.lean \\
        --def-name dist \\
        --downstream Mathlib.Data.Nat.Dist Archive.Imo.Imo2024Q5 \\
        --timeout 300 \\
        --output-dir experiments/001/run1
"""

from __future__ import annotations

import argparse
import difflib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from lean_rewrite.candidates import DefNotFoundError, def_to_abbrev, remove_redundant_unfolds
from lean_rewrite.evaluator import EvalResult, evaluate


def _git_worktree_add(mathlib: Path, dest: Path) -> None:
    subprocess.run(
        ["git", "worktree", "add", str(dest), "HEAD"],
        cwd=str(mathlib),
        check=True,
        capture_output=True,
        text=True,
    )


def _lake_cache_get(worktree: Path, lake: str = "lake") -> None:
    subprocess.run(
        [lake, "exe", "cache", "get"],
        cwd=str(worktree),
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )


def _git_worktree_remove(mathlib: Path, dest: Path) -> None:
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(dest)],
        cwd=str(mathlib),
        capture_output=True,
        text=True,
    )


def is_improvement(result: EvalResult) -> bool:
    """True when builds all succeed and unfold usage improves.

    Improvement means either the candidate source has fewer unfold calls
    (delta < 0) OR the baseline already had unfold calls that abbrev-ification
    makes redundant no-ops (baseline > 0).
    """
    return result.all_succeeded and (
        result.total_unfold_count_delta < 0 or result.total_unfold_count_baseline > 0
    )


def format_report(result: EvalResult, improved: bool) -> str:
    total_loc_delta = sum(c.proof_loc_delta for c in result.comparisons if c.both_succeeded)
    lines = [
        f"Definition:             {result.def_name}",
        f"Baseline worktree:      {result.baseline_worktree}",
        f"Candidate worktree:     {result.candidate_worktree}",
        f"All builds succeeded:   {result.all_succeeded}",
        f"Wall time delta (sum):  {result.total_wall_time_delta:+.2f}s",
        f"Baseline unfold count:  {result.total_unfold_count_baseline}",
        f"Unfold count delta:     {result.total_unfold_count_delta:+d}",
        f"Proof LOC delta:        {total_loc_delta:+d}",
        "",
    ]
    for comp in result.comparisons:
        lines.append(f"  Module: {comp.module}")
        lines.append(f"    Both succeeded: {comp.both_succeeded}")
        if comp.both_succeeded:
            lines.append(f"    Wall time delta:   {comp.wall_time_delta:+.2f}s")
            lines.append(f"    Unfold count delta: {comp.unfold_count_delta:+d}")
            lines.append(f"    Proof LOC delta:    {comp.proof_loc_delta:+d}")
        else:
            if not comp.baseline.build.success:
                lines.append(f"    Baseline FAILED (rc={comp.baseline.build.returncode})")
            if not comp.candidate.build.success:
                lines.append(f"    Candidate FAILED (rc={comp.candidate.build.returncode})")

    lines.append("")
    if improved:
        lines.append("VERDICT: IMPROVED — patch accepted")
    else:
        lines.append("VERDICT: REJECTED")
        if not result.all_succeeded:
            lines.append("  Reason: one or more builds failed")
        else:
            lines.append("  Reason: no unfold reduction and no baseline unfold calls")

    return "\n".join(lines)


def make_patch(target_file: str, original: str, candidate: str) -> str:
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        candidate.splitlines(keepends=True),
        fromfile=f"a/{target_file}",
        tofile=f"b/{target_file}",
    )
    return "".join(diff)


def _module_to_file(module: str) -> str:
    return module.replace(".", "/") + ".lean"


def run_pipeline(
    mathlib: Path,
    target_file: str,
    def_name: str,
    downstream: list[str],
    *,
    timeout: float | None = None,
    lake: str = "lake",
    output_dir: Path | None = None,
    remove_unfolds: bool = False,
    inject_profiler: bool = False,
) -> int:
    """Run the full pipeline. Returns 0 on improvement, 1 on reject, 2 on error."""
    src_path = mathlib / target_file
    if not src_path.exists():
        print(f"ERROR: target file not found: {src_path}", file=sys.stderr)
        return 2

    original_source = src_path.read_text(encoding="utf-8")
    try:
        candidate_source = def_to_abbrev(original_source, def_name)
    except DefNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if candidate_source == original_source:
        print("INFO: No change produced (already abbrev or @[reducible]).")
        return 1

    # Create ephemeral candidate worktree (git worktree add requires the dir to not exist)
    tmp_base = tempfile.mkdtemp(prefix="lr-wt-")
    wt_path = Path(tmp_base) / "cand"
    try:
        _git_worktree_add(mathlib, wt_path)
        _lake_cache_get(wt_path, lake=lake)
        (wt_path / target_file).write_text(candidate_source, encoding="utf-8")

        if remove_unfolds:
            for mod in downstream:
                ds_path = wt_path / _module_to_file(mod)
                if ds_path.exists():
                    original_ds = ds_path.read_text(encoding="utf-8")
                    modified_ds = remove_redundant_unfolds(original_ds, def_name)
                    if modified_ds != original_ds:
                        ds_path.write_text(modified_ds, encoding="utf-8")

        result = evaluate(
            baseline_worktree=mathlib,
            candidate_worktree=wt_path,
            modules=downstream,
            def_name=def_name,
            timeout=timeout,
            lake=lake,
            inject_profiler=inject_profiler,
        )

        improved = is_improvement(result)
        report = format_report(result, improved)
        print(report)

        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "report.txt").write_text(report, encoding="utf-8")
            if improved:
                patch = make_patch(target_file, original_source, candidate_source)
                (output_dir / "candidate.patch").write_text(patch, encoding="utf-8")
                print(f"Patch: {output_dir / 'candidate.patch'}")
            print(f"Report: {output_dir / 'report.txt'}")

        return 0 if improved else 1

    finally:
        try:
            _git_worktree_remove(mathlib, wt_path)
        except Exception:
            pass
        shutil.rmtree(tmp_base, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Propose def→abbrev rewrites for a Lean 4 definition and evaluate the effect."
    )
    parser.add_argument("--mathlib", required=True, type=Path, help="Path to mathlib4 clone")
    parser.add_argument(
        "--file", required=True, dest="target_file",
        help="Target Lean file (relative to --mathlib)"
    )
    parser.add_argument("--def-name", required=True, help="Name of the def to transform")
    parser.add_argument(
        "--downstream", nargs="+", required=True, metavar="MODULE",
        help="Downstream modules to build and evaluate"
    )
    parser.add_argument(
        "--timeout", type=float, default=None,
        help="Per-module build timeout in seconds"
    )
    parser.add_argument("--lake", default="lake", help="lake binary name or path")
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="Write report.txt (and candidate.patch if improved) here"
    )
    parser.add_argument(
        "--remove-unfolds", action="store_true", default=False,
        help="Also remove redundant `unfold <def-name>` calls from downstream files"
    )
    parser.add_argument(
        "--inject-profiler", action="store_true", default=False,
        help="Prepend `set_option profiler true` to module files before building"
    )

    args = parser.parse_args()
    sys.exit(
        run_pipeline(
            mathlib=args.mathlib,
            target_file=args.target_file,
            def_name=args.def_name,
            downstream=args.downstream,
            timeout=args.timeout,
            lake=args.lake,
            output_dir=args.output_dir,
            remove_unfolds=args.remove_unfolds,
            inject_profiler=args.inject_profiler,
        )
    )


if __name__ == "__main__":
    main()
