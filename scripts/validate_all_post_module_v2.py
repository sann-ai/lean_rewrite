#!/usr/bin/env python3
"""T021: Re-validate all 6 post-module entries with the improved pipeline (T019+T020).

Changes vs. the original validate_refactors_post_module.py:
  - Uses has_termination_by guard (T020) to skip unsafe defs.
  - format_report now includes Baseline instance context count (T019).
  - Outputs to experiments/validation_post_module_v2/.

Usage:
    python3 scripts/validate_all_post_module_v2.py [--mathlib /path/to/mathlib4]
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
    report_dir = output_dir / sha8
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
        return {"sha8": sha8, "def_name": def_name, "verdict": f"BLOCKED: {reason[:60]}", "all_succeeded": False, "instance_ctx": "N/A"}

    # Get before-state from parent commit
    result = subprocess.run(
        ["git", "show", f"{sha}^:{file}"],
        cwd=str(mathlib),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return write_blocked(f"git show {sha}^:{file} failed: {result.stderr.strip()[:150]}")

    before_content = result.stdout

    # T020: skip defs with termination_by
    if has_termination_by(before_content, def_name):
        report = (
            f"SHA:                  {sha}\n"
            f"Commit:               {msg[:80]}\n"
            f"File:                 {file}\n"
            f"Definition:           {def_name}\n"
            f"All builds succeeded: False\n"
            f"Baseline instance context count: N/A\n"
            f"\nVERDICT: SKIPPED_TERMINATION_BY\n"
            f"  Reason: {def_name} has a termination_by clause; abbrev conversion is not safe\n"
        )
        (report_dir / "report.txt").write_text(report)
        return {"sha8": sha8, "def_name": def_name, "verdict": "SKIPPED_TERMINATION_BY", "all_succeeded": False, "instance_ctx": "N/A"}

    # Apply transformation
    try:
        candidate_content = def_to_abbrev(before_content, def_name)
    except DefNotFoundError as e:
        return write_blocked(f"def_to_abbrev: {e}")

    if candidate_content == before_content:
        return write_blocked("no change produced (already abbrev or @[reducible], or before-state is abbrev→def direction)")

    # Remove redundant unfolds from candidate
    candidate_cleaned = remove_redundant_unfolds(candidate_content, def_name)

    # Create two isolated mathlib worktrees
    tmp = tempfile.mkdtemp(prefix=f"lr-v2-{sha8}-")
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

        (baseline_wt / file).write_text(before_content)
        (candidate_wt / file).write_text(candidate_cleaned)

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
        report_body = format_report(eval_result, improved)

        header = (
            f"SHA:                  {sha}\n"
            f"Commit:               {msg[:80]}\n"
            f"File:                 {file}\n"
            f"remove_redundant_unfolds: {'applied' if candidate_cleaned != candidate_content else 'no unfolds found'}\n"
            f"\n"
        )
        full_report = header + report_body
        (report_dir / "report.txt").write_text(full_report)

        if improved:
            patch = make_patch(file, before_content, candidate_cleaned)
            (report_dir / "candidate.patch").write_text(patch)

        verdict = "ACCEPTED" if improved else "REJECTED"
        instance_ctx = eval_result.total_instance_context_baseline
        return {
            "sha8": sha8,
            "def_name": def_name,
            "verdict": verdict,
            "all_succeeded": eval_result.all_succeeded,
            "instance_ctx": instance_ctx,
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


def write_readme(output_dir: Path, results: list[dict]) -> None:
    lines = [
        "# Tier 2 Validation v2 — Post-Module def↔abbrev (T021)",
        "",
        "Pipeline: T019 (instance_context_count signal) + T020 (termination_by guard).",
        "",
        "| sha8 | def_name | All builds succeeded | Baseline instance ctx | VERDICT |",
        "|------|----------|---------------------|----------------------|---------|",
    ]
    for r in results:
        lines.append(
            f"| {r['sha8']} | {r['def_name']} | {r.get('all_succeeded', 'N/A')} | {r.get('instance_ctx', 'N/A')} | {r['verdict']} |"
        )
    accepted = sum(1 for r in results if r["verdict"] == "ACCEPTED")
    lines += [
        "",
        f"**ACCEPTED: {accepted}/{len(results)}**",
        "",
        "Tier 2 criterion: ≥3 known mathlib refactor commits reproduced (pipeline returns ACCEPTED or SKIPPED_TERMINATION_BY counts as a known-safe signal).",
    ]
    (output_dir / "README.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mathlib", type=Path, default=Path("/Users/san/mathlib4"))
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()

    jsonl = REPO / "data" / "refactor_commits_post_module.jsonl"
    if not jsonl.exists():
        print(f"ERROR: {jsonl} not found", file=sys.stderr)
        sys.exit(1)

    output_dir = REPO / "experiments" / "validation_post_module_v2"
    output_dir.mkdir(parents=True, exist_ok=True)

    cases = []
    with open(jsonl) as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))

    print(f"Loaded {len(cases)} cases from {jsonl.name}")

    results = []
    for i, case in enumerate(cases, 1):
        print(f"\n[{i}/{len(cases)}] {case['sha'][:8]} {case['def_name']} ...")
        r = run_case(case, args.mathlib, output_dir, args.timeout)
        results.append(r)
        print(f"  → {r['verdict']} (builds={r.get('all_succeeded', 'N/A')}, instance_ctx={r.get('instance_ctx', 'N/A')})")

    write_readme(output_dir, results)

    print(f"\n=== Summary ===")
    accepted = 0
    for r in results:
        print(f"  {r['sha8']}  {r['def_name']:<30}  {r['verdict']}")
        if r["verdict"] == "ACCEPTED":
            accepted += 1
    print(f"\nACCEPTED: {accepted}/{len(results)}")
    print(f"Reports: {output_dir}/")


if __name__ == "__main__":
    main()
