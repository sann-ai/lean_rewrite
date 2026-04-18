#!/usr/bin/env python3
"""
Fetch mathlib4 refactor/perf commits after the module-system introduction
that change exactly one def/abbrev block in a single .lean file,
filtering to def↔abbrev changes only.

Usage:
    python3 scripts/fetch_refactor_commits_post_module.py [--mathlib PATH] [--after-sha SHA] [--output PATH] [--extra-prefixes feat,fix,style]

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


DEFAULT_EXTRA_PREFIXES = ("feat", "fix", "style")


def get_candidate_shas_after(
    mathlib: Path, after_sha: str, extra_prefixes: tuple[str, ...] = ()
) -> list[tuple[str, str]]:
    """Return (sha, subject) pairs for commits after after_sha that are likely def↔abbrev changes.

    Base criteria: subject starts with refactor/perf/chore OR contains the word 'abbrev'.
    Extra prefixes (e.g. feat, fix, style) can be added via extra_prefixes.
    """
    log = _git(
        "log", f"{after_sha}..HEAD", "--format=%H\t%s", "--no-merges", cwd=mathlib
    )
    all_prefixes = ("refactor", "perf", "chore") + tuple(extra_prefixes)
    result = []
    for line in log.splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition("\t")
        subj = subject.strip().lower()
        if any(subj.startswith(p) for p in all_prefixes) or "abbrev" in subj:
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


def load_existing_records(output: Path) -> dict[str, dict]:
    """Load existing jsonl records keyed by sha."""
    if not output.exists():
        return {}
    records = {}
    with open(output, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                records[rec["sha"]] = rec
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mathlib", type=Path, default=DEFAULT_MATHLIB)
    parser.add_argument(
        "--after-sha",
        default=MODULE_SYSTEM_SHA,
        help="Only scan commits after this SHA (exclusive)",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--extra-prefixes",
        default=",".join(DEFAULT_EXTRA_PREFIXES),
        help="Comma-separated additional commit subject prefixes to scan (default: feat,fix,style)",
    )
    args = parser.parse_args(argv)

    if not args.mathlib.is_dir():
        print(f"error: mathlib not found at {args.mathlib}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)

    extra_prefixes = tuple(p.strip() for p in args.extra_prefixes.split(",") if p.strip())

    # Load existing records for deduplication
    existing = load_existing_records(args.output)
    print(
        f"Loaded {len(existing)} existing records from {args.output}",
        file=sys.stderr,
    )

    print(
        f"Scanning extra-prefix commits ({', '.join(extra_prefixes)}) after {args.after_sha} in {args.mathlib} …",
        file=sys.stderr,
    )
    # Only fetch candidates matching the extra prefixes (base prefixes already covered)
    candidates = get_candidate_shas_after(args.mathlib, args.after_sha, extra_prefixes=extra_prefixes)
    # Remove SHAs already in the base set (matched by base prefixes) — filter to only new candidates
    # Actually, get_candidate_shas_after includes base prefixes too; that's fine since we deduplicate by sha.
    print(f"Found {len(candidates)} candidate commits to check.", file=sys.stderr)

    new_records: list[dict] = []
    for i, (sha, message) in enumerate(candidates):
        if sha in existing:
            continue
        record = process_commit(sha, message, args.mathlib)
        if record:
            new_records.append(record)
            print(f"  [{len(new_records):3d}] {sha[:8]}  {message[:60]}", file=sys.stderr)
        if (i + 1) % 100 == 0:
            print(
                f"  … {i+1}/{len(candidates)} scanned, {len(new_records)} new found so far",
                file=sys.stderr,
            )

    # Merge: existing + new, preserve order (existing first)
    all_records = list(existing.values()) + new_records
    with open(args.output, "w", encoding="utf-8") as f:
        for rec in all_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(
        f"\nScanned {len(candidates)} commits; found {len(new_records)} new records "
        f"(total: {len(all_records)}) → {args.output}",
        file=sys.stderr,
    )
    if len(all_records) == 0:
        print("WARNING: 0 records total — dataset may need a wider search scope.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
