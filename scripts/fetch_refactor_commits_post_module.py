#!/usr/bin/env python3
"""
Fetch mathlib4 refactor/perf commits after the module-system introduction
that change exactly one def/abbrev block in a single .lean file,
filtering to def↔abbrev changes only.

Usage:
    python3 scripts/fetch_refactor_commits_post_module.py [--mathlib PATH] [--after-sha SHA] [--output PATH]

Output: data/refactor_commits_post_module.jsonl
Fields: sha, message, file, def_name, before_def, after_def
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Re-use parsing utilities from the original script
sys.path.insert(0, str(Path(__file__).parent))
from fetch_refactor_commits import (
    _DEF_HEADER_RE,
    _git,
    find_changed_blocks,
    get_changed_lean_files,
    get_file_at,
)

DEFAULT_MATHLIB = Path("/Users/san/mathlib4")
DEFAULT_OUTPUT = Path(__file__).parent.parent / "data" / "refactor_commits_post_module.jsonl"
# SHA of the commit that migrated Mathlib to the module system (Dec 2024)
MODULE_SYSTEM_SHA = "6a54a80825"


def get_candidate_shas_after(mathlib: Path, after_sha: str) -> list[tuple[str, str]]:
    """Return (sha, subject) pairs for commits after after_sha that are likely def↔abbrev changes.

    Criteria: subject starts with refactor/perf/chore OR contains the word 'abbrev'.
    This is broader than the original script because post-module-system def→abbrev
    changes in mathlib typically use 'chore' prefix, not 'refactor'/'perf'.
    """
    log = _git(
        "log", f"{after_sha}..HEAD", "--format=%H\t%s", "--no-merges", cwd=mathlib
    )
    result = []
    for line in log.splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition("\t")
        subj = subject.strip().lower()
        if (
            subj.startswith("refactor")
            or subj.startswith("perf")
            or subj.startswith("chore")
            or "abbrev" in subj
        ):
            result.append((sha, subject.strip()))
    return result


def _get_def_keyword(block: str) -> str | None:
    """Return the primary keyword ('def' or 'abbrev') of a block, or None."""
    for line in block.splitlines():
        m = _DEF_HEADER_RE.match(line)
        if m:
            return m.group(1)
    return None


def is_def_to_abbrev_change(before_def: str, after_def: str) -> bool:
    """Return True if the change is def→abbrev or abbrev→def."""
    kw_before = _get_def_keyword(before_def)
    kw_after = _get_def_keyword(after_def)
    if kw_before is None or kw_after is None:
        return False
    return (kw_before == "def" and kw_after == "abbrev") or (
        kw_before == "abbrev" and kw_after == "def"
    )


def process_commit(sha: str, message: str, mathlib: Path) -> dict | None:
    """Return a record dict if the commit changes exactly one block from def↔abbrev.

    Other block changes in the same commit are allowed; only the def↔abbrev block
    is captured. If multiple def↔abbrev blocks are changed, the commit is skipped
    (ambiguous which one is the primary change).
    """
    lean_files = get_changed_lean_files(sha, mathlib)
    if len(lean_files) != 1:
        return None

    filepath = lean_files[0]
    before = get_file_at(f"{sha}^", filepath, mathlib)
    after = get_file_at(sha, filepath, mathlib)
    if before is None or after is None:
        return None

    changed = find_changed_blocks(before, after)
    abbrev_changes = [
        (name, b, a) for name, b, a in changed if is_def_to_abbrev_change(b, a)
    ]
    if len(abbrev_changes) != 1:
        return None

    def_name, before_def, after_def = abbrev_changes[0]
    return {
        "sha": sha,
        "message": message,
        "file": filepath,
        "def_name": def_name,
        "before_def": before_def,
        "after_def": after_def,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mathlib", type=Path, default=DEFAULT_MATHLIB)
    parser.add_argument(
        "--after-sha",
        default=MODULE_SYSTEM_SHA,
        help="Only scan commits after this SHA (exclusive)",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    if not args.mathlib.is_dir():
        print(f"error: mathlib not found at {args.mathlib}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)

    print(
        f"Scanning refactor/perf commits after {args.after_sha} in {args.mathlib} …",
        file=sys.stderr,
    )
    candidates = get_candidate_shas_after(args.mathlib, args.after_sha)
    print(f"Found {len(candidates)} refactor/perf commits to check.", file=sys.stderr)

    records: list[dict] = []
    for i, (sha, message) in enumerate(candidates):
        record = process_commit(sha, message, args.mathlib)
        if record:
            records.append(record)
            print(f"  [{len(records):3d}] {sha[:8]}  {message[:60]}", file=sys.stderr)
        if (i + 1) % 50 == 0:
            print(
                f"  … {i+1}/{len(candidates)} scanned, {len(records)} found so far",
                file=sys.stderr,
            )

    with open(args.output, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\nWrote {len(records)} records to {args.output}", file=sys.stderr)
    if len(records) == 0:
        print("WARNING: 0 records found — dataset may need a wider search scope.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
