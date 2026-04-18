#!/usr/bin/env python3
"""
Fetch mathlib4 refactor/perf commits that change exactly one def/structure/class.

Usage:
    python3 scripts/fetch_refactor_commits.py [--mathlib PATH] [--limit N] [--output PATH]

Output: data/refactor_commits.jsonl
Fields: sha, message, file, def_name, before_def, after_def
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_MATHLIB = Path("/Users/san/mathlib4")
DEFAULT_OUTPUT = Path(__file__).parent.parent / "data" / "refactor_commits.jsonl"
DEFAULT_LIMIT = 30000
TARGET_COUNT = 50

# Top-level keywords that start a new block at column 0
_TOP_LEVEL_RE = re.compile(
    r"^(?:@\[|protected\b|private\b|noncomputable\b|partial\b|unsafe\b|"
    r"theorem\b|lemma\b|def\b|abbrev\b|structure\b|class\b|instance\b|"
    r"example\b|#|namespace\b|section\b|end\b|open\b|variable\b|universe\b|"
    r"attribute\b|set_option\b|mutual\b)"
)

# Matches a top-level def/abbrev/structure/class header at column 0
_DEF_HEADER_RE = re.compile(
    r"^(?:(?:protected|private|noncomputable|partial|unsafe)\s+)*"
    r"(def|abbrev|structure|class)\s+(\w[\w.']*)",
)


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, args, result.stdout, result.stderr
        )
    return result.stdout


def get_candidate_shas(mathlib: Path, limit: int) -> list[tuple[str, str]]:
    """Return (sha, subject) pairs for refactor/perf commits (no merges)."""
    log = _git("log", "--format=%H\t%s", f"-{limit}", "--no-merges", cwd=mathlib)
    result = []
    for line in log.splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition("\t")
        subj = subject.strip().lower()
        if subj.startswith("refactor") or subj.startswith("perf"):
            result.append((sha, subject.strip()))
    return result


def get_changed_lean_files(sha: str, mathlib: Path) -> list[str]:
    """Return .lean files changed in this commit."""
    try:
        out = _git("diff-tree", "--no-commit-id", "-r", "--name-only", sha, cwd=mathlib)
    except subprocess.CalledProcessError:
        return []
    return [f.strip() for f in out.splitlines() if f.strip().endswith(".lean")]


def get_file_at(ref: str, filepath: str, mathlib: Path) -> str | None:
    """Return file content at a given git ref, or None if not found."""
    try:
        return _git("show", f"{ref}:{filepath}", cwd=mathlib)
    except subprocess.CalledProcessError:
        return None


def extract_all_def_blocks(source: str) -> dict[str, str]:
    """
    Return a dict mapping def_name → full block text for every top-level
    def/abbrev/structure/class in source.
    """
    lines = source.splitlines(keepends=True)
    # Find positions of all top-level def/structure/class starts
    starts: list[tuple[int, str]] = []  # (line_index, def_name)
    for i, line in enumerate(lines):
        m = _DEF_HEADER_RE.match(line)
        if m:
            starts.append((i, m.group(2)))

    blocks: dict[str, str] = {}
    for idx, (start, name) in enumerate(starts):
        # Walk backwards to include preceding attribute lines
        block_start = start
        i = start - 1
        while i >= 0:
            prev = lines[i]
            if prev.strip() == "" or prev.startswith("@[") or prev.startswith("/--"):
                block_start = i
                i -= 1
            else:
                break

        # End is the start of the next top-level block, or EOF
        if idx + 1 < len(starts):
            end = starts[idx + 1][0]
            # Also walk backwards from next start to skip its attribute lines
            i = end - 1
            while i > start and (lines[i].strip() == "" or lines[i].startswith("@[") or lines[i].startswith("/--")):
                i -= 1
            end = i + 1
        else:
            end = len(lines)

        block = "".join(lines[block_start:end]).rstrip() + "\n"
        blocks[name] = block

    return blocks


def extract_def_block(source: str, def_name: str) -> str | None:
    """Extract a single named def block from source."""
    blocks = extract_all_def_blocks(source)
    return blocks.get(def_name)


def find_changed_def_names(diff_text: str) -> set[str]:
    """
    Parse unified diff to find top-level def/structure/class names
    that appear in added or removed lines (fast pre-filter).
    """
    changed: set[str] = set()
    for line in diff_text.splitlines():
        if not line.startswith(("+", "-")) or line.startswith(("+++", "---")):
            continue
        content = line[1:]
        m = _DEF_HEADER_RE.match(content)
        if m:
            changed.add(m.group(2))
    return changed


def find_changed_blocks(
    before: str, after: str
) -> list[tuple[str, str, str]]:
    """
    Compare def blocks between before and after source.
    Returns list of (def_name, before_block, after_block) for blocks that changed.
    Only includes blocks that existed in both versions.
    """
    before_blocks = extract_all_def_blocks(before)
    after_blocks = extract_all_def_blocks(after)

    changed = []
    for name, before_block in before_blocks.items():
        if name in after_blocks and after_blocks[name] != before_block:
            changed.append((name, before_block, after_blocks[name]))
    return changed


def process_commit(sha: str, message: str, mathlib: Path) -> dict | None:
    """Return a record dict or None if the commit doesn't qualify."""
    lean_files = get_changed_lean_files(sha, mathlib)
    if len(lean_files) != 1:
        return None

    filepath = lean_files[0]

    before = get_file_at(f"{sha}^", filepath, mathlib)
    after = get_file_at(sha, filepath, mathlib)
    if before is None or after is None:
        return None

    changed = find_changed_blocks(before, after)
    if len(changed) != 1:
        return None

    def_name, before_def, after_def = changed[0]
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
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Max recent commits to scan",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    if not args.mathlib.is_dir():
        print(f"error: mathlib not found at {args.mathlib}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)

    print(f"Scanning up to {args.limit} commits in {args.mathlib} …", file=sys.stderr)
    candidates = get_candidate_shas(args.mathlib, args.limit)
    print(f"Found {len(candidates)} refactor/perf commits to check.", file=sys.stderr)

    records: list[dict] = []
    for i, (sha, message) in enumerate(candidates):
        record = process_commit(sha, message, args.mathlib)
        if record:
            records.append(record)
            print(
                f"  [{len(records):3d}] {sha[:8]}  {message[:60]}", file=sys.stderr
            )
        if (i + 1) % 200 == 0:
            print(
                f"  … {i+1}/{len(candidates)} scanned, {len(records)} found so far",
                file=sys.stderr,
            )
        if len(records) >= TARGET_COUNT * 4:
            print(f"Reached {len(records)} records, stopping early.", file=sys.stderr)
            break

    with open(args.output, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\nWrote {len(records)} records to {args.output}", file=sys.stderr)
    if len(records) < TARGET_COUNT:
        print(
            f"WARNING: only {len(records)} records found (target: {TARGET_COUNT}).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
