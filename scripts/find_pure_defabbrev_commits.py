#!/usr/bin/env python3
"""T029: Find mathlib4 commits where a def→abbrev keyword-only change is the primary change.

Strategy: parse unified diff hunks. A "pure" def→abbrev commit is one where:
  - Exactly 1 Lean file changed
  - At least 1 hunk changes ONLY `def <name>` → `abbrev <name>` (same name, same rest of line)
  - No other removed/added lines in that specific hunk (the def header line is the only ± line)
  - The def name is findable in the before-state

Scans up to --max-commits commits since the module-system SHA.
Excludes SHAs already in refactor_commits_post_module.jsonl.

Usage:
    python3 scripts/find_pure_defabbrev_commits.py [--mathlib PATH] [--max-commits N]

Output: data/pure_defabbrev_commits.jsonl
Fields: sha, message, file, def_name, before_def, after_def
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_refactor_commits import _git, extract_all_def_blocks, get_changed_lean_files

DEFAULT_MATHLIB = Path("/Users/san/mathlib4")
MODULE_SYSTEM_SHA = "6a54a80825"
DEFAULT_OUTPUT = Path(__file__).parent.parent / "data" / "pure_defabbrev_commits.jsonl"
EXISTING_JSONL = Path(__file__).parent.parent / "data" / "refactor_commits_post_module.jsonl"

_DEF_LINE_RE = re.compile(
    r'^(?:(?:protected|private|noncomputable|partial|unsafe)\s+)*def\s+(\w[\w.\']*)',
)
_ABBREV_LINE_RE = re.compile(
    r'^(?:(?:protected|private|noncomputable|partial|unsafe)\s+)*abbrev\s+(\w[\w.\']*)',
)


def get_all_shas(mathlib: Path, after_sha: str, max_commits: int) -> list[tuple[str, str]]:
    log = _git(
        "log", f"{after_sha}..HEAD", f"-{max_commits}",
        "--format=%H\t%s", "--no-merges", cwd=mathlib,
    )
    result = []
    for line in log.splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition("\t")
        result.append((sha.strip(), subject.strip()))
    return result


def get_file_at(ref: str, filepath: str, mathlib: Path) -> str | None:
    try:
        return _git("show", f"{ref}:{filepath}", cwd=mathlib)
    except subprocess.CalledProcessError:
        return None


def parse_hunks(diff_text: str) -> list[list[str]]:
    """Split unified diff into hunks (list of lines per hunk)."""
    hunks = []
    current: list[str] | None = None
    for line in diff_text.splitlines():
        if line.startswith('@@'):
            if current is not None:
                hunks.append(current)
            current = [line]
        elif current is not None:
            current.append(line)
    if current:
        hunks.append(current)
    return hunks


def find_pure_defabbrev_hunk(diff_text: str) -> str | None:
    """Return def_name if the diff contains a hunk where ONLY a def→abbrev rename happens."""
    hunks = parse_hunks(diff_text)
    for hunk in hunks:
        removed = [l[1:] for l in hunk if l.startswith('-') and not l.startswith('---')]
        added = [l[1:] for l in hunk if l.startswith('+') and not l.startswith('+++')]
        if len(removed) != 1 or len(added) != 1:
            continue
        rm = removed[0].strip()
        ad = added[0].strip()
        m_rm = _DEF_LINE_RE.match(rm)
        m_ad = _ABBREV_LINE_RE.match(ad)
        if not m_rm or not m_ad:
            continue
        if m_rm.group(1) != m_ad.group(1):
            continue
        # Verify the rest of the line (after keyword+name) is identical
        rm_rest = rm[m_rm.end():]
        ad_rest = ad[m_ad.end():]
        if rm_rest == ad_rest:
            return m_rm.group(1)
    return None


def load_existing_shas(*jsonl_paths: Path) -> set[str]:
    shas: set[str] = set()
    for p in jsonl_paths:
        if not p.exists():
            continue
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        shas.add(json.loads(line)["sha"])
                    except (json.JSONDecodeError, KeyError):
                        pass
    return shas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mathlib", type=Path, default=DEFAULT_MATHLIB)
    parser.add_argument("--max-commits", type=int, default=1000)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    if not args.mathlib.is_dir():
        print(f"error: mathlib not found at {args.mathlib}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    existing_shas = load_existing_shas(EXISTING_JSONL, args.output)
    print(f"Skipping {len(existing_shas)} already-known SHAs.", file=sys.stderr)

    print(f"Fetching up to {args.max_commits} commits since {MODULE_SYSTEM_SHA} …", file=sys.stderr)
    all_shas = get_all_shas(args.mathlib, MODULE_SYSTEM_SHA, args.max_commits)
    print(f"Got {len(all_shas)} commits.", file=sys.stderr)

    records: list[dict] = []

    for i, (sha, msg) in enumerate(all_shas):
        if sha in existing_shas:
            continue
        lean_files = get_changed_lean_files(sha, args.mathlib)
        if len(lean_files) != 1:
            continue

        filepath = lean_files[0]
        try:
            diff_out = _git("show", sha, "--", filepath, cwd=args.mathlib)
        except subprocess.CalledProcessError:
            continue

        def_name = find_pure_defabbrev_hunk(diff_out)
        if def_name is None:
            continue

        # Get before/after block for the record
        before = get_file_at(f"{sha}^", filepath, args.mathlib)
        after = get_file_at(sha, filepath, args.mathlib)
        if before is None or after is None:
            continue

        bb = extract_all_def_blocks(before)
        ab = extract_all_def_blocks(after)
        before_def = bb.get(def_name, "")
        after_def = ab.get(def_name, "")

        records.append({
            "sha": sha,
            "message": msg,
            "file": filepath,
            "def_name": def_name,
            "before_def": before_def,
            "after_def": after_def,
        })
        print(f"  FOUND [{len(records):3d}]: {sha[:8]}  {def_name}  ({msg[:60]})", file=sys.stderr)

        if (i + 1) % 200 == 0:
            print(f"  … {i+1}/{len(all_shas)} checked, {len(records)} found", file=sys.stderr)

    # Load previously saved records (if any) and merge
    prev_records: list[dict] = []
    if args.output.exists():
        with open(args.output) as f:
            for line in f:
                line = line.strip()
                if line:
                    prev_records.append(json.loads(line))

    all_records = prev_records + records
    with open(args.output, "w", encoding="utf-8") as f:
        for rec in all_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\nNew: {len(records)}, total: {len(all_records)} → {args.output}", file=sys.stderr)
    return 0 if len(all_records) >= 3 else 1


if __name__ == "__main__":
    sys.exit(main())
