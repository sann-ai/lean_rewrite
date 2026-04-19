#!/usr/bin/env python3
"""T029: Validate pure def→abbrev commits from data/pure_defabbrev_commits.jsonl.

For each entry (up to --max-cases), runs the pipeline:
  - git show sha^:<file> to get before-state
  - apply def_to_abbrev + remove_redundant_unfolds
  - create two mathlib worktrees, build both, compare metrics
  - report saved to experiments/validation_v3/<sha8>/report.txt

Usage:
    python3 scripts/validate_pure_defabbrev.py [--mathlib PATH] [--max-cases N] [--timeout SEC]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "src"))

from lean_rewrite.candidates import DefNotFoundError, def_to_abbrev, has_termination_by, remove_redundant_unfolds
from lean_rewrite.evaluator import evaluate
from lean_rewrite.main import format_report, is_improvement, make_patch


def file_to_module(file_path: str) -> str:
    return file_path.replace("/", ".").removesuffix(".lean")


def run_case(case: dict, mathlib: Path, output_dir: Path, timeout: float) -> dict:
    sha = case["sha"]
    sha8 = sha[:8]
    file = case["file"]
    def_name = case["def_name"]
    msg = case.get("message", "")
    safe_name = def_name.replace("'", "p").replace("/", "_").replace(" ", "_")
    report_dir = output_dir / f"{sha8}_{safe_name}"
    report_dir.mkdir(parents=True, exist_ok=True)

    def write_blocked(reason: str) -> dict:
        report = (
            f"SHA:                  {sha}\n"
            f"Commit:               {msg[:80]}\n"
            f"File:                 {file}\n"
            f"Definition:           {def_name}\n"
            f"All builds succeeded: False\n"
            f"Baseline instance context count: N/A\n"
            f"\nVERDICT: BLOCKED — {reason}\n"
        )
        (report_dir / "report.txt").write_text(report)
        return {"sha8": sha8, "def_name": def_name, "verdict": f"BLOCKED: {reason[:60]}", "all_succeeded": False}

    result = subprocess.run(
        ["git", "show", f"{sha}^:{file}"],
        cwd=str(mathlib),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return write_blocked(f"git show {sha}^:{file} failed: {result.stderr.strip()[:150]}")

    before_content = result.stdout

    if has_termination_by(before_content, def_name):
        report = (
            f"SHA:                  {sha}\n"
            f"Commit:               {msg[:80]}\n"
            f"File:                 {file}\n"
            f"Definition:           {def_name}\n"
            f"All builds succeeded: False\n"
            f"Baseline instance context count: N/A\n"
            f"\nVERDICT: SKIPPED_TERMINATION_BY\n"
            f"  Reason: {def_name} has a termination_by clause\n"
        )
        (report_dir / "report.txt").write_text(report)
        return {"sha8": sha8, "def_name": def_name, "verdict": "SKIPPED_TERMINATION_BY", "all_succeeded": False}

    try:
        candidate_content = def_to_abbrev(before_content, def_name)
    except DefNotFoundError as e:
        return write_blocked(f"def_to_abbrev: {e}")

    if candidate_content == before_content:
        return write_blocked("no change produced")

    candidate_cleaned = remove_redundant_unfolds(candidate_content, def_name)

    tmp = tempfile.mkdtemp(prefix=f"lr-v3-{sha8}-")
    baseline_wt = Path(tmp) / "baseline"
    candidate_wt = Path(tmp) / "candidate"
    try:
        for wt in (baseline_wt, candidate_wt):
            subprocess.run(
                ["git", "worktree", "add", str(wt), "HEAD"],
                cwd=str(mathlib), check=True, capture_output=True,
            )

        (baseline_wt / file).write_text(before_content)
        (candidate_wt / file).write_text(candidate_cleaned)

        for wt in (baseline_wt, candidate_wt):
            subprocess.run(
                ["lake", "exe", "cache", "get"],
                cwd=str(wt), check=False, capture_output=True, timeout=900,
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
        report_body = format_report(eval_result, improved)

        header = (
            f"SHA:                  {sha}\n"
            f"Commit:               {msg[:80]}\n"
            f"File:                 {file}\n"
            f"remove_redundant_unfolds: {'applied' if candidate_cleaned != candidate_content else 'none found'}\n"
            f"\n"
        )
        (report_dir / "report.txt").write_text(header + report_body)

        if improved:
            patch = make_patch(file, before_content, candidate_cleaned)
            (report_dir / "candidate.patch").write_text(patch)

        verdict = "ACCEPTED" if improved else "REJECTED"
        return {
            "sha8": sha8,
            "def_name": def_name,
            "verdict": verdict,
            "all_succeeded": eval_result.all_succeeded,
        }

    except Exception as exc:
        return write_blocked(f"exception: {exc}")
    finally:
        for wt in (baseline_wt, candidate_wt):
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(wt)],
                cwd=str(mathlib), capture_output=True,
            )
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mathlib", type=Path, default=Path("/Users/san/mathlib4"))
    parser.add_argument("--max-cases", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()

    jsonl = REPO / "data" / "pure_defabbrev_commits.jsonl"
    if not jsonl.exists():
        print(f"ERROR: {jsonl} not found — run find_pure_defabbrev_commits.py first", file=sys.stderr)
        sys.exit(1)

    output_dir = REPO / "experiments" / "validation_v3"
    output_dir.mkdir(parents=True, exist_ok=True)

    cases = []
    with open(jsonl) as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))

    # Skip cases already validated
    cases_to_run = []
    for c in cases:
        sha8 = c["sha"][:8]
        safe_name = c["def_name"].replace("'", "p").replace("/", "_").replace(" ", "_")
        report = output_dir / f"{sha8}_{safe_name}" / "report.txt"
        if not report.exists():
            cases_to_run.append(c)

    cases_to_run = cases_to_run[:args.max_cases]
    print(f"Loaded {len(cases)} cases; {len(cases_to_run)} to run (max {args.max_cases})")

    results = []
    for i, case in enumerate(cases_to_run, 1):
        print(f"\n[{i}/{len(cases_to_run)}] {case['sha'][:8]} {case['def_name']} ({case.get('message','')[:50]}) ...")
        r = run_case(case, args.mathlib, output_dir, args.timeout)
        results.append(r)
        print(f"  → {r['verdict']} (builds={r.get('all_succeeded', 'N/A')})")

    # Also count already-done results for cumulative tally
    all_verdicts = {}
    for c in cases:
        sha8 = c["sha"][:8]
        safe_name = c["def_name"].replace("'", "p").replace("/", "_").replace(" ", "_")
        report = output_dir / f"{sha8}_{safe_name}" / "report.txt"
        if report.exists():
            txt = report.read_text()
            if "VERDICT: ACCEPTED" in txt or "VERDICT: IMPROVED" in txt:
                all_verdicts[sha8] = "ACCEPTED"
            elif "VERDICT: REJECTED" in txt:
                all_verdicts[sha8] = "REJECTED"
            elif "VERDICT: BLOCKED" in txt:
                all_verdicts[sha8] = "BLOCKED"
            elif "VERDICT: SKIPPED" in txt:
                all_verdicts[sha8] = "SKIPPED"

    accepted_v3 = sum(1 for v in all_verdicts.values() if v == "ACCEPTED")
    print(f"\n=== Summary ===")
    for r in results:
        print(f"  {r['sha8']}  {r['def_name']:<30}  {r['verdict']}")
    print(f"\nACCEPTED in validation_v3: {accepted_v3}/{len(all_verdicts)}")
    # T021 gave 1 ACCEPTED (6f0e175f SkewPolynomial)
    total_accepted = accepted_v3 + 1
    print(f"Cumulative ACCEPTED (T021: 1 + T029: {accepted_v3}): {total_accepted}")
    print(f"Tier 2 criterion (≥3): {'MET' if total_accepted >= 3 else 'NOT YET'}")
    print(f"\nReports: {output_dir}/")


if __name__ == "__main__":
    main()
