#!/usr/bin/env python3
"""
Find defs in mathlib4 that are good candidates for @[simp] attribute addition.

Criteria:
  (a) def itself does NOT have @[simp]
  (b) same file has at least 1 @[simp] lemma/theorem that references def_name
  (c) same file has at least 1 `unfold def_name` occurrence (downstream dependency)

Outputs top 10 results to data/simp_eligible_defs.jsonl
"""
import re
import json
import os
import sys
from pathlib import Path
from collections import defaultdict

MATHLIB = Path("/Users/san/mathlib4/Mathlib")
OUTPUT_JSONL = Path(__file__).parent.parent / "data" / "simp_eligible_defs.jsonl"

# Regex: top-level def declaration (allowing indentation for namespace blocks)
# Matches: optional @[...] on previous line, then modifiers, then `def name`
DEF_HEADER_RE = re.compile(
    r'^(?P<indent>[ \t]*)(?:noncomputable\s+|protected\s+|private\s+|unsafe\s+|partial\s+)*'
    r'def\s+(?P<name>[A-Za-z][A-Za-z0-9_\']*)',
    re.MULTILINE
)
SIMP_ATTR_LINE_RE = re.compile(r'@\[(?:[^\]]*\b)?simp\b(?:[^\]]*)\]')
UNFOLD_RE = re.compile(r'\bunfold\s+(?:[A-Za-z][A-Za-z0-9_.]*)\.(?P<name>[A-Za-z][A-Za-z0-9_\']*)\b|\bunfold\s+(?P<bare>[A-Za-z][A-Za-z0-9_\']*)\b')


def extract_defs_from_source(source: str) -> list[dict]:
    """Return list of {name, start, header_line_idx, has_simp_attr, is_noncomputable}."""
    lines = source.splitlines()
    results = []
    for m in DEF_HEADER_RE.finditer(source):
        name = m.group("name")
        pos = m.start()
        # find which line this is
        line_idx = source[:pos].count('\n')
        # check for @[simp] attr: scan up from header line
        has_simp = False
        is_noncomputable = False
        for back in range(1, 6):
            if line_idx - back < 0:
                break
            prev = lines[line_idx - back].strip()
            if prev.startswith('@['):
                if 'simp' in prev:
                    has_simp = True
                # keep scanning in case multiple attr lines
            elif prev.startswith('/--') or prev.startswith('--'):
                continue  # doc comment, skip
            else:
                break
        # also check inline on def line
        header_line = lines[line_idx]
        if 'noncomputable' in header_line or (line_idx > 0 and 'noncomputable' in lines[line_idx - 1]):
            is_noncomputable = True
        results.append({
            'name': name,
            'line_idx': line_idx,
            'has_simp_attr': has_simp,
            'is_noncomputable': is_noncomputable,
        })
    return results


def count_simp_lemmas_referencing(source: str, def_name: str) -> int:
    """Count @[simp] lemma/theorem blocks that reference def_name."""
    lines = source.splitlines()
    count = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        if SIMP_ATTR_LINE_RE.search(line):
            # Look ahead in the next ~10 lines for def_name reference
            snippet = '\n'.join(lines[i:i+12])
            # Match def_name as a word boundary (unqualified or last component)
            if re.search(r'\b' + re.escape(def_name) + r'\b', snippet):
                count += 1
        i += 1
    return count


def count_unfold_references(source: str, def_name: str) -> int:
    """Count `unfold def_name` or `unfold Foo.def_name` occurrences."""
    pattern = re.compile(
        r'\bunfold\s+(?:[A-Za-z][A-Za-z0-9_.]*)?' + re.escape(def_name) + r'\b'
    )
    return len(pattern.findall(source))


def scan_directory(mathlib_dir: Path, max_files: int = 5000) -> list[dict]:
    """Scan Mathlib directory for simp-eligible defs."""
    candidates = []
    files = list(mathlib_dir.rglob("*.lean"))
    print(f"Scanning {len(files)} .lean files...", file=sys.stderr)

    for i, fpath in enumerate(files[:max_files]):
        if i % 500 == 0:
            print(f"  {i}/{len(files)}", file=sys.stderr)
        try:
            source = fpath.read_text(encoding='utf-8', errors='replace')
        except Exception:
            continue

        defs = extract_defs_from_source(source)
        for d in defs:
            if d['has_simp_attr']:
                continue  # already @[simp]
            name = d['name']

            simp_count = count_simp_lemmas_referencing(source, name)
            unfold_count = count_unfold_references(source, name)

            if simp_count >= 1 and unfold_count >= 1:
                candidates.append({
                    'file': str(fpath.relative_to(mathlib_dir.parent)),
                    'def_name': name,
                    'simp_lemma_count': simp_count,
                    'downstream_unfold_count': unfold_count,
                    'is_noncomputable': d['is_noncomputable'],
                    '_line_idx': d['line_idx'],
                })

    # Sort by total signal strength (unfold_count first, then simp_lemma_count)
    candidates.sort(key=lambda x: (x['downstream_unfold_count'] + x['simp_lemma_count']), reverse=True)
    return candidates


def main():
    candidates = scan_directory(MATHLIB)
    print(f"Found {len(candidates)} candidates", file=sys.stderr)

    # Deduplicate by def_name (take best file for each name)
    seen_names = set()
    deduped = []
    for c in candidates:
        if c['def_name'] not in seen_names:
            seen_names.add(c['def_name'])
            deduped.append(c)

    top10 = deduped[:10]
    OUTPUT_JSONL.parent.mkdir(exist_ok=True)
    with open(OUTPUT_JSONL, 'w') as f:
        for entry in top10:
            row = {k: v for k, v in entry.items() if not k.startswith('_')}
            f.write(json.dumps(row) + '\n')

    print(f"Wrote {len(top10)} entries to {OUTPUT_JSONL}", file=sys.stderr)
    for c in top10:
        print(f"  {c['def_name']:30s}  unfold={c['downstream_unfold_count']:3d}  simp={c['simp_lemma_count']:3d}  {c['file']}")


if __name__ == '__main__':
    main()
