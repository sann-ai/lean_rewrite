#!/usr/bin/env python3
"""Validate pipeline against data/refactor_commits_post_module.jsonl (post-module-system).

All entries are processed (4 total).  For each:
  - create two mathlib worktrees at HEAD
  - write before-state into both (baseline and candidate)
  - apply def_to_abbrev to the candidate
  - apply remove_redundant_unfolds to the candidate (equivalent to --remove-unfolds)
  - run evaluate() and record the result

Results are saved to experiments/validation_post_module/<sha8>/report.txt.

Usage:
    python3 scripts/validate_refactors_post_module.py [--mathlib /path/to/mathlib4]
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

from lean_rewrite.candidates import DefNotFoundError, def_to_abbrev, remove_redundant_unfolds
from lean_rewrite.evaluator import evaluate
from lean_rewrite.main import format_report, is_improvement, make_patch


def file_to_module(file_path: str) -> str:
    """Mathlib/Data/Prod/TProd.lean → Mathlib.Data.Prod.TProd"""
    return file_path.replace("/", ".").removesuffix(".lean")


def load_all_cases(jsonl_path: Path) -> list[dict]:
    entries = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def run_case(
    case: dict,
    mathlib: Path,
    output_dir: Path,
    timeout: float = 600,
) -> dict:
    sha = case["sha"]
    sha8 = sha[:8]
    file = case["file"]
    def_name = case["def_name"]
    msg = case.get("message", "")
    report_dir = output_dir / sha8
    report_dir.mkdir(parents=True, exist_ok=True)

    def write_blocked(reason: str) -> dict:
        report = (
            f"SHA:                  {sha}\n"
            f"Commit:               {msg[:80]}\n"
            f"File:                 {file}\n"
            f"Definition:           {def_name}\n"
            f"All builds succeeded: False\n"
            f"\nVERDICT: BLOCKED — {reason}\n"
        )
        (report_dir / "report.txt").write_text(report)
        return {"sha8": sha8, "def_name": def_name, "status": "blocked", "reason": reason}

    # Retrieve before-state from git history (parent of commit)
    result = subprocess.run(
        ["git", "show", f"{sha}^:{file}"],
        cwd=str(mathlib),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return write_blocked(f"git show {sha}^:{file} failed: {result.stderr.strip()[:200]}")

    before_content = result.stdout

    # Apply def→abbrev transformation
    try:
        candidate_content = def_to_abbrev(before_content, def_name)
    except DefNotFoundError as e:
        return write_blocked(f"def_to_abbrev: {e}")

    if candidate_content == before_content:
        direction = ""
        if re.search(r"\babbrev\s+" + re.escape(def_name) + r"\b", before_content):
            direction = " (before-state already abbrev — abbrev→def commit, pipeline skips)"
        return write_blocked(f"no change produced{direction}")

    # Apply remove_redundant_unfolds to candidate (same module file)
    candidate_content_cleaned = remove_redundant_unfolds(candidate_content, def_name)

    # Create two isolated mathlib worktrees
    tmp = tempfile.mkdtemp(prefix=f"lr-val-pm-{sha8}-")
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

        # Overwrite files with before / candidate versions
        (baseline_wt / file).write_text(before_content)
        (candidate_wt / file).write_text(candidate_content_cleaned)

        # Populate lake cache from shared parent clone
        for wt in (baseline_wt, candidate_wt):
            subprocess.run(
                ["lake", "exe", "cache", "get"],
                cwd=str(wt),
                check=False,
                capture_output=True,
                timeout=900,
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

        header = (
            f"SHA:                  {sha}\n"
            f"Commit:               {msg[:80]}\n"
            f"File:                 {file}\n"
            f"remove_redundant_unfolds applied: "
            f"{'yes' if candidate_content_cleaned != candidate_content else 'no (no unfolds found)'}\n"
            f"\n"
        )
        full_report = header + report_text
        (report_dir / "report.txt").write_text(full_report)

        if improved:
            patch = make_patch(file, before_content, candidate_content_cleaned)
            (report_dir / "candidate.patch").write_text(patch)

        return {
            "sha8": sha8,
            "def_name": def_name,
            "status": "accepted" if improved else "rejected",
            "all_succeeded": eval_result.all_succeeded,
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
    )
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()

    jsonl = REPO / "data" / "refactor_commits_post_module.jsonl"
    if not jsonl.exists():
        print(f"ERROR: {jsonl} not found", file=sys.stderr)
        sys.exit(1)

    output_dir = REPO / "experiments" / "validation_post_module"
    output_dir.mkdir(parents=True, exist_ok=True)

    cases = load_all_cases(jsonl)
    print(f"Loaded {len(cases)} cases from {jsonl.name}")
    for c in cases:
        before_kw = c["before_def"].split()[0] if c["before_def"].strip() else "?"
        after_kw = c["after_def"].split()[0] if c["after_def"].strip() else "?"
        print(f"  {c['sha'][:8]}  {c['file']}  def:{c['def_name']}  [{before_kw}→{after_kw}]")

    results = []
    for i, case in enumerate(cases, 1):
        print(f"\n[{i}/{len(cases)}] {case['sha'][:8]} ({case['def_name']}) ...")
        r = run_case(case, args.mathlib, output_dir, timeout=args.timeout)
        results.append(r)
        print(f"  → {r['status']}" + (f": {r.get('reason', '')}" if r["status"] == "blocked" else ""))

    print(f"\n=== Summary ===")
    for r in results:
        print(f"  {r['sha8']}  {r['def_name']}  → {r['status']}")

    reports_written = sum(1 for r in results if (output_dir / r["sha8"] / "report.txt").exists())
    print(f"\n{reports_written}/{len(cases)} reports written to {output_dir.relative_to(REPO)}/")


if __name__ == "__main__":
    main()
