#!/usr/bin/env python3
"""Validate that our pipeline reproduces known refactors from data/refactor_commits.jsonl.

Selects 3 cases (preferring def→abbrev entries), reverts each target file to its
before-state in an ephemeral mathlib4 worktree, applies our def_to_abbrev transformation,
and runs the evaluator.  Results are saved to experiments/validation/<sha8>/report.txt.

Usage:
    python3 scripts/validate_refactors.py [--mathlib /path/to/mathlib4]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "src"))

from lean_rewrite.candidates import DefNotFoundError, def_to_abbrev
from lean_rewrite.evaluator import evaluate
from lean_rewrite.main import format_report, is_improvement, make_patch


def file_to_module(file_path: str) -> str:
    """Mathlib/Data/Prod/TProd.lean → Mathlib.Data.Prod.TProd"""
    return file_path.replace("/", ".").removesuffix(".lean")


def select_cases(jsonl_path: Path, n: int = 3) -> list[dict]:
    """Return n cases from the JSONL, preferring def→abbrev over def→def."""
    entries = []
    with open(jsonl_path) as f:
        for line in f:
            entries.append(json.loads(line))

    # Priority 1: any entry where before has 'def' keyword and after has 'abbrev' keyword
    def_to_abbrev_cases = [
        e for e in entries
        if re.search(r"\bdef\s+", e.get("before_def", ""))
        and re.search(r"\babbrev\s+", e.get("after_def", ""))
    ]

    # Priority 2: simple def→def (small blocks, fill remaining slots)
    def_to_def_cases = [
        e for e in entries
        if re.search(r"\bdef\s+", e.get("before_def", ""))
        and e not in def_to_abbrev_cases
    ]
    def_to_def_cases.sort(key=lambda e: len(e.get("before_def", "")))

    selected = list(def_to_abbrev_cases[:n])
    remaining = n - len(selected)
    selected.extend(def_to_def_cases[:remaining])
    return selected[:n]


def run_case(
    case: dict,
    mathlib: Path,
    output_dir: Path,
    timeout: float = 300,
) -> dict:
    """Run pipeline on one historical case.  Returns a summary dict."""
    sha = case["sha"]
    sha8 = sha[:8]
    file = case["file"]
    def_name = case["def_name"]
    msg = case.get("message", "")
    report_dir = output_dir / sha8
    report_dir.mkdir(parents=True, exist_ok=True)

    def write_blocked(reason: str) -> dict:
        report = (
            f"Definition:           {def_name}\n"
            f"SHA:                  {sha}\n"
            f"File:                 {file}\n"
            f"All builds succeeded: False\n"
            f"\nVERDICT: BLOCKED — {reason}\n"
        )
        (report_dir / "report.txt").write_text(report)
        return {"sha8": sha8, "def_name": def_name, "status": "blocked", "reason": reason}

    # Get before-state file content
    result = subprocess.run(
        ["git", "show", f"{sha}^:{file}"],
        cwd=str(mathlib),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return write_blocked(f"git show {sha}^:{file} failed: {result.stderr.strip()[:200]}")

    before_content = result.stdout

    # Apply def→abbrev transformation (text level)
    try:
        candidate_content = def_to_abbrev(before_content, def_name)
    except DefNotFoundError as e:
        return write_blocked(f"def_to_abbrev: {e}")

    if candidate_content == before_content:
        return write_blocked("no change produced (def already abbrev or @[reducible])")

    # Check whether the file uses old import syntax (pre-module-system, Dec 2024)
    # Old syntax: "import Mathlib.X"  New syntax: "public import Mathlib.X" / "module"
    uses_old_imports = bool(
        re.search(r"^import Mathlib\.", before_content, re.MULTILINE)
    )

    # Create two isolated mathlib worktrees
    tmp = tempfile.mkdtemp(prefix=f"lr-val-{sha8}-")
    baseline_wt = Path(tmp) / "baseline"
    candidate_wt = Path(tmp) / "candidate"
    try:
        for wt in (baseline_wt, candidate_wt):
            subprocess.run(
                ["git", "worktree", "add", str(wt), "HEAD"],
                cwd=str(mathlib),
                check=True,
                capture_output=True,
            )

        # Write the before / candidate versions
        (baseline_wt / file).write_text(before_content)
        (candidate_wt / file).write_text(candidate_content)

        # Populate lake cache (shared via symlinks from parent clone)
        for wt in (baseline_wt, candidate_wt):
            subprocess.run(
                ["lake", "exe", "cache", "get"],
                cwd=str(wt),
                check=False,
                capture_output=True,
                timeout=600,
            )

        downstream = [file_to_module(file)]
        eval_result = evaluate(
            baseline_worktree=baseline_wt,
            candidate_worktree=candidate_wt,
            modules=downstream,
            def_name=def_name,
            timeout=timeout,
            lake="lake",
        )

        improved = is_improvement(eval_result)
        report_text = format_report(eval_result, improved)

        # Annotate report with provenance
        header = (
            f"SHA:                  {sha}\n"
            f"Commit:               {msg[:80]}\n"
            f"File:                 {file}\n"
        )
        if uses_old_imports:
            header += (
                "Note: before-state uses pre-module-system import syntax; "
                "build failure likely due to toolchain incompatibility.\n"
            )
        header += "\n"
        full_report = header + report_text
        (report_dir / "report.txt").write_text(full_report)

        if improved:
            patch = make_patch(file, before_content, candidate_content)
            (report_dir / "candidate.patch").write_text(patch)

        return {
            "sha8": sha8,
            "def_name": def_name,
            "status": "accepted" if improved else "rejected",
            "all_succeeded": eval_result.all_succeeded,
            "old_imports": uses_old_imports,
        }

    except Exception as exc:
        return write_blocked(f"exception: {exc}")

    finally:
        for wt in (baseline_wt, candidate_wt):
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(wt)],
                cwd=str(mathlib),
                capture_output=True,
            )
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mathlib", type=Path, default=Path("/Users/san/mathlib4"),
        help="Path to the shared mathlib4 clone (read-only; worktrees are ephemeral)."
    )
    parser.add_argument(
        "--timeout", type=float, default=300,
        help="Per-module build timeout in seconds (default: 300)."
    )
    parser.add_argument(
        "--n", type=int, default=3,
        help="Number of cases to validate (default: 3)."
    )
    args = parser.parse_args()

    jsonl = REPO / "data" / "refactor_commits.jsonl"
    output_dir = REPO / "experiments" / "validation"
    output_dir.mkdir(parents=True, exist_ok=True)

    cases = select_cases(jsonl, n=args.n)
    print(f"Selected {len(cases)} cases:")
    for c in cases:
        before_word = c["before_def"].split()[0] if c["before_def"] else "?"
        after_word = c["after_def"].split()[0] if c["after_def"] else "?"
        print(f"  {c['sha'][:8]}  {c['file']}  def:{c['def_name']}  [{before_word}→{after_word}]")

    results = []
    for i, case in enumerate(cases, 1):
        print(f"\n[{i}/{len(cases)}] {case['sha'][:8]} ({case['def_name']}) ...")
        r = run_case(case, args.mathlib, output_dir, timeout=args.timeout)
        results.append(r)
        print(f"  → {r['status']}" + (f" (old_imports={r.get('old_imports')})" if "old_imports" in r else ""))

    reports = [r for r in results if (output_dir / r["sha8"] / "report.txt").exists()]
    print(f"\n{len(reports)}/{len(cases)} reports written to {output_dir.relative_to(REPO)}/")
    for r in results:
        print(f"  {r['sha8']}  {r['def_name']}  → {r['status']}")


if __name__ == "__main__":
    main()
