#!/usr/bin/env python3
"""
Find defs in mathlib4 with >=5 downstream theorem/lemma/example references in the same file.

Criteria:
  (a) def does NOT have @[simp] attribute
  (b) same file has >=5 theorem/lemma/example blocks that reference the def_name
  (c) is_noncomputable: False (build verification is realistic)

Outputs top 10 results to data/tier4_candidates.jsonl
Fields: file, def_name, downstream_theorem_count, is_noncomputable
"""
import re
import json
import sys
from pathlib import Path

MATHLIB = Path("/Users/san/mathlib4/Mathlib")
OUTPUT_JSONL = Path(__file__).parent.parent / "data" / "tier4_candidates.jsonl"

DEF_HEADER_RE = re.compile(
    r'^(?P<indent>[ \t]*)(?:noncomputable\s+|protected\s+|private\s+|unsafe\s+|partial\s+)*'
    r'def\s+(?P<name>[A-Za-z][A-Za-z0-9_\']*)',
    re.MULTILINE,
)

# Matches start of a theorem/lemma/example block
THLEM_START_RE = re.compile(
    r'^\s*(?:@\[[^\]]*\]\s*)*(?:private\s+|protected\s+)?(?:theorem|lemma|example)\b',
    re.MULTILINE,
)

SIMP_ATTR_RE = re.compile(r'@\[(?:[^\]]*\b)?simp\b(?:[^\]]*)\]')


def has_simp_attr(lines: list[str], line_idx: int) -> bool:
    """Check if the def at line_idx has @[simp] in its attribute lines above."""
    for back in range(1, 6):
        if line_idx - back < 0:
            break
        prev = lines[line_idx - back].strip()
        if prev.startswith('@['):
            if SIMP_ATTR_RE.search(prev):
                return True
        elif prev.startswith('/--') or prev.startswith('--'):
            continue
        else:
            break
    return False


def count_downstream_theorem_refs(source: str, def_name: str) -> int:
    """
    Count theorem/lemma/example blocks (in the same file, outside the def block)
    that contain def_name as a word boundary.
    """
    word_re = re.compile(r'\b' + re.escape(def_name) + r'\b')
    # Find all theorem/lemma/example start positions
    block_starts = [m.start() for m in THLEM_START_RE.finditer(source)]
    if not block_starts:
        return 0

    count = 0
    for i, start in enumerate(block_starts):
        end = block_starts[i + 1] if i + 1 < len(block_starts) else len(source)
        block = source[start:end]
        if word_re.search(block):
            count += 1
    return count


def scan_directory(mathlib_dir: Path) -> list[dict]:
    files = list(mathlib_dir.rglob("*.lean"))
    print(f"Scanning {len(files)} .lean files...", file=sys.stderr)
    candidates = []

    for i, fpath in enumerate(files):
        if i % 500 == 0:
            print(f"  {i}/{len(files)}", file=sys.stderr)
        try:
            source = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        lines = source.splitlines()

        for m in DEF_HEADER_RE.finditer(source):
            name = m.group("name")
            line_idx = source[: m.start()].count("\n")

            is_noncomputable = "noncomputable" in m.group(0) or (
                line_idx > 0 and "noncomputable" in lines[line_idx - 1]
            )
            if is_noncomputable:
                continue  # skip: build verification unrealistic

            if has_simp_attr(lines, line_idx):
                continue  # already @[simp]

            count = count_downstream_theorem_refs(source, name)
            if count >= 5:
                candidates.append(
                    {
                        "file": str(fpath.relative_to(mathlib_dir.parent)),
                        "def_name": name,
                        "downstream_theorem_count": count,
                        "is_noncomputable": False,
                    }
                )

    candidates.sort(key=lambda x: x["downstream_theorem_count"], reverse=True)
    return candidates


def main():
    candidates = scan_directory(MATHLIB)
    print(f"Found {len(candidates)} candidates total", file=sys.stderr)

    # Deduplicate by def_name (keep highest count)
    seen: set[str] = set()
    deduped: list[dict] = []
    for c in candidates:
        if c["def_name"] not in seen:
            seen.add(c["def_name"])
            deduped.append(c)

    top10 = deduped[:10]
    OUTPUT_JSONL.parent.mkdir(exist_ok=True)
    with open(OUTPUT_JSONL, "w") as f:
        for entry in top10:
            f.write(json.dumps(entry) + "\n")

    print(f"Wrote {len(top10)} entries to {OUTPUT_JSONL}", file=sys.stderr)
    for c in top10:
        print(
            f"  {c['def_name']:35s}  downstream={c['downstream_theorem_count']:4d}  {c['file']}"
        )


if __name__ == "__main__":
    main()
