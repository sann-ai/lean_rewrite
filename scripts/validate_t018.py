#!/usr/bin/env python3
"""T018: validate 2 new post-module entries (f3acad5a, a04c5481)."""
from __future__ import annotations

import json
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

TARGET_SHAS = {"f3acad5a", "a04c5481"}
MATHLIB = Path("/Users/san/mathlib4")
TIMEOUT = 600.0
OUTPUT_DIR = REPO / "experiments" / "validation_post_module"


def file_to_module(file_path: str) -> str:
    return file_path.replace("/", ".").removesuffix(".lean")


def run_case(case: dict) -> dict:
    sha = case["sha"]
    sha8 = sha[:8]
    file = case["file"]
    def_name = case["def_name"]
    msg = case.get("message", "")
    report_dir = OUTPUT_DIR / sha8
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

    result = subprocess.run(
        ["git", "show", f"{sha}^:{file}"],
        cwd=str(MATHLIB),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return write_blocked(f"git show failed: {result.stderr.strip()[:200]}")

    before_content = result.stdout

    try:
        candidate_content = def_to_abbrev(before_content, def_name)
    except DefNotFoundError as e:
        return write_blocked(f"def_to_abbrev: {e}")

    if candidate_content == before_content:
        return write_blocked("no change produced")

    candidate_content_cleaned = remove_redundant_unfolds(candidate_content, def_name)

    tmp = tempfile.mkdtemp(prefix=f"lr-val-t018-{sha8}-")
    baseline_wt = Path(tmp) / "baseline"
    candidate_wt = Path(tmp) / "candidate"
    try:
        for wt in (baseline_wt, candidate_wt):
            subprocess.run(
                ["git", "worktree", "add", str(wt), "HEAD"],
                cwd=str(MATHLIB),
                check=True,
                capture_output=True,
            )

        (baseline_wt / file).write_text(before_content)
        (candidate_wt / file).write_text(candidate_content_cleaned)

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
            timeout=TIMEOUT,
            lake="lake",
        )

        improved = is_improvement(eval_result)
        report_text = format_report(eval_result, improved)

        unfold_changed = candidate_content_cleaned != candidate_content
        header = (
            f"SHA:                  {sha}\n"
            f"Commit:               {msg[:80]}\n"
            f"File:                 {file}\n"
            f"Definition:           {def_name}\n"
            f"remove_redundant_unfolds: {'yes' if unfold_changed else 'no (no unfolds found)'}\n\n"
        )
        (report_dir / "report.txt").write_text(header + report_text)

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
                cwd=str(MATHLIB),
                capture_output=True,
            )
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    jsonl = REPO / "data" / "refactor_commits_post_module.jsonl"
    cases = []
    with open(jsonl) as f:
        for line in f:
            line = line.strip()
            if line:
                entry = json.loads(line)
                if entry["sha"][:8] in TARGET_SHAS:
                    cases.append(entry)

    print(f"Running T018 validation for {len(cases)} cases: {[c['sha'][:8] for c in cases]}")
    results = []
    for i, case in enumerate(cases, 1):
        print(f"\n[{i}/{len(cases)}] {case['sha'][:8]} ({case['def_name']}) ...")
        r = run_case(case)
        results.append(r)
        extra = f": {r.get('reason','')}" if r["status"] == "blocked" else ""
        print(f"  → {r['status']}{extra}")

    print("\n=== T018 Results ===")
    for r in results:
        print(f"  {r['sha8']}  {r['def_name']}  → {r['status']}")


if __name__ == "__main__":
    main()
