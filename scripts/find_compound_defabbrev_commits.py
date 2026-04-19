#!/usr/bin/env python3
"""T032: Find mathlib4 commits with BOTH def→abbrev AND unfold removal.

Strategy: scan commit diffs for commits that:
  (a) Change `def <name>` → `abbrev <name>` in some Lean file
  (b) Also remove at least one `unfold <name>` line elsewhere in the same diff

These "compound" commits are the best pipeline validation targets because
their before-states necessarily have unfold calls (criterion b).

Scans up to --max-commits commits since the module-system SHA.

Usage:
    python3 scripts/find_compound_defabbrev_commits.py [--mathlib PATH] [--max-commits N]

Output: data/compound_defabbrev_commits.jsonl
Fields: sha, message, file, def_name, removed_unfold_count, before_def, after_def
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_refactor_commits import _git, extract_all_def_blocks

DEFAULT_MATHLIB = Path("/Users/san/mathlib4")
MODULE_SYSTEM_SHA = "6a54a80825"
DEFAULT_OUTPUT = Path(__file__).parent.parent / "data" / "compound_defabbrev_commits.jsonl"

_DEF_LINE_RE = re.compile(
    r'^(?:(?:protected|private|noncomputable|partial|unsafe)\s+)*def\s+(\w[\w.\']*)',
)
_ABBREV_LINE_RE = re.compile(
    r'^(?:(?:protected|private|noncomputable|partial|unsafe)\s+)*(?:@\[[^\]]*\]\s*)*abbrev\s+(\w[\w.\']*)',
)
_REDUCIBLE_LINE_RE = re.compile(
    r'^\+\s*@\[reducible\]',
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


def get_full_diff(sha: str, mathlib: Path) -> str:
    """Return full unified diff for this commit."""
    try:
        return _git("diff-tree", "--no-commit-id", "-r", "-p", sha, cwd=mathlib)
    except subprocess.CalledProcessError:
        return ""


def parse_per_file_diff(diff_text: str) -> dict[str, list[str]]:
    """Split unified diff into per-file sections, keyed by filename."""
    result: dict[str, list[str]] = {}
    current_file: str | None = None
    current_lines: list[str] = []

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            if current_file:
                result[current_file] = current_lines
            current_file = None
            current_lines = [line]
        elif line.startswith("+++ b/") and current_file is None:
            # Extract the filename from "+++ b/<path>"
            fname = line[6:]
            current_file = fname
            current_lines.append(line)
        else:
            if current_file is not None:
                current_lines.append(line)
            else:
                current_lines.append(line)

    if current_file:
        result[current_file] = current_lines

    return result


def find_defabbrev_change(file_lines: list[str]) -> str | None:
    """Return def_name if file diff contains def→abbrev rename."""
    removed_defs: dict[str, str] = {}  # name → rest of line
    added_abbrevs: dict[str, str] = {}

    for line in file_lines:
        if line.startswith("-") and not line.startswith("---"):
            content = line[1:].strip()
            m = _DEF_LINE_RE.match(content)
            if m:
                removed_defs[m.group(1)] = content[m.end():]
        elif line.startswith("+") and not line.startswith("+++"):
            content = line[1:].strip()
            m = _ABBREV_LINE_RE.match(content)
            if m:
                added_abbrevs[m.group(1)] = content[m.end():]

    for name in removed_defs:
        if name in added_abbrevs:
            return name
    return None


def count_removed_unfolds(diff_text: str, def_name: str) -> int:
    """Count lines in diff that remove `unfold <def_name>` calls."""
    escaped = re.escape(def_name)
    pattern = re.compile(rf'^-\s*unfold\s+(?:[\w.]+\.)?{escaped}\b')
    count = 0
    for line in diff_text.splitlines():
        if pattern.match(line):
            count += 1
    return count


def count_downstream_removed_refs(diff_text: str, def_name: str, def_file: str) -> int:
    """Count removed lines in NON-def files that reference <def_name> in proofs.

    This catches broader downstream changes: removed simp/rw/show calls that
    reference the def by name, not just `unfold <name>` lines.
    """
    escaped = re.escape(def_name)
    ref_pattern = re.compile(rf'\b{escaped}\b')
    count = 0
    in_target_file = False
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            in_target_file = (f"b/{def_file}" in line)
        elif not in_target_file and line.startswith("-") and not line.startswith("---"):
            content = line[1:]
            if ref_pattern.search(content):
                count += 1
    return count


def get_file_at(sha: str, filepath: str, mathlib: Path) -> str | None:
    try:
        return _git("show", f"{sha}:{filepath}", cwd=mathlib)
    except subprocess.CalledProcessError:
        return None


def load_existing_shas(output: Path) -> set[str]:
    shas: set[str] = set()
    if not output.exists():
        return shas
    with open(output) as f:
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
    parser.add_argument("--max-commits", type=int, default=2000)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    if not args.mathlib.is_dir():
        print(f"error: mathlib not found at {args.mathlib}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    existing_shas = load_existing_shas(args.output)
    print(f"Skipping {len(existing_shas)} already-known SHAs.", file=sys.stderr)

    print(f"Fetching up to {args.max_commits} commits since {MODULE_SYSTEM_SHA} …", file=sys.stderr)
    all_shas = get_all_shas(args.mathlib, MODULE_SYSTEM_SHA, args.max_commits)
    print(f"Got {len(all_shas)} commits to scan.", file=sys.stderr)

    records: list[dict] = []

    for i, (sha, msg) in enumerate(all_shas):
        if sha in existing_shas:
            continue

        diff_text = get_full_diff(sha, args.mathlib)
        if not diff_text:
            continue

        per_file = parse_per_file_diff(diff_text)
        lean_files = [f for f in per_file if f.endswith(".lean")]
        if not lean_files:
            continue

        for filepath in lean_files:
            file_lines = per_file[filepath]
            def_name = find_defabbrev_change(file_lines)
            if def_name is None:
                continue

            removed_unfold_count = count_removed_unfolds(diff_text, def_name)
            downstream_ref_count = count_downstream_removed_refs(diff_text, def_name, filepath)
            # Require at least one downstream reference removal (unfold or other)
            if removed_unfold_count == 0 and downstream_ref_count == 0:
                continue

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
                "removed_unfold_count": removed_unfold_count,
                "downstream_ref_count": downstream_ref_count,
                "before_def": before_def,
                "after_def": after_def,
            })
            print(f"  FOUND [{len(records):3d}]: {sha[:8]}  {def_name}  unfolds={removed_unfold_count}  downstream_refs={downstream_ref_count}  ({msg[:50]})", file=sys.stderr)

        if (i + 1) % 500 == 0:
            print(f"  … {i+1}/{len(all_shas)} checked, {len(records)} found so far", file=sys.stderr)

    # Merge with existing records
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
    if len(all_records) == 0:
        print("NOTE: 0 compound commits found. Will record as observation in NOTEBOOK.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
