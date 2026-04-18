"""Rewrite candidates for Lean 4 definitions.

Currently supports a single transformation: ``def → abbrev`` (or
``@[reducible] def`` when ``noncomputable`` is present, since ``abbrev`` itself
must be computable in Lean 4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# Modifiers that can appear between attributes/doc comment and ``def``.
# Order can vary in practice, so we match any combination.
_MODIFIERS = ("noncomputable", "protected", "private", "partial", "unsafe")

# ``abbrev`` is incompatible with ``noncomputable`` and ``partial`` (abbrev must
# reduce; partial defs have no equational compiler). When either is present we
# fall back to ``@[reducible] def``.
_ABBREV_INCOMPATIBLE = {"noncomputable", "partial"}


class DefNotFoundError(ValueError):
    """Raised when ``def_name`` does not appear as a top-level ``def`` in source."""


@dataclass
class _DefMatch:
    """Structured view of a ``def`` declaration's leading header."""

    header_start: int  # start of first modifier (or ``def`` if no modifiers)
    def_kw_start: int  # index of the literal ``def`` keyword
    def_kw_end: int  # index just past the ``def`` keyword
    modifiers: list[str]  # preserved modifier tokens in source order


def _is_ident_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_" or ch == "'"


def _find_def(source: str, def_name: str) -> _DefMatch:
    """Locate a top-level ``def <name>`` declaration in ``source``.

    Walks each ``def`` keyword occurrence, verifies the following identifier
    matches ``def_name``, and verifies the line context before ``def`` is only
    whitespace + modifiers (meaning ``def`` is genuinely at top level on its
    line, not e.g. ``let def ...`` inside a body or an unrelated substring).
    """
    name_pat = re.escape(def_name)
    # Find every ``def <def_name>`` with proper word boundaries.
    candidate_re = re.compile(
        rf"\bdef\s+{name_pat}(?=[\s\.\(\{{\[:])"
    )

    for m in candidate_re.finditer(source):
        def_kw_start = m.start()
        def_kw_end = def_kw_start + len("def")

        # Check the text from start of line to ``def_kw_start``: it must be
        # whitespace and (optionally) a sequence of modifier tokens, and
        # nothing else. This rules out matches like ``let def foo ...``,
        # ``theorem bar : def foo ...``, or substrings inside a comment line.
        line_start = source.rfind("\n", 0, def_kw_start) + 1
        prefix = source[line_start:def_kw_start]
        stripped = prefix.strip()
        if stripped:
            tokens = stripped.split()
            if not all(tok in _MODIFIERS for tok in tokens):
                continue

        # Now walk backward across whitespace + preceding lines that consist
        # solely of modifier tokens, to collect multi-line modifier sequences.
        modifiers: list[str] = []
        cursor = def_kw_start
        # First, consume modifiers on the same line (already verified above).
        for tok in prefix.split():
            modifiers.append(tok)
        # Move cursor to start of line where the first same-line modifier began
        # (or to def_kw_start if there were none).
        if modifiers:
            # Find position of first modifier token in the source.
            first_mod = modifiers[0]
            # Look for it within [line_start, def_kw_start].
            first_mod_idx = source.find(first_mod, line_start, def_kw_start)
            cursor = first_mod_idx
        # Walk up across lines above that consist solely of modifier tokens.
        while cursor > 0:
            prev_line_end = cursor - 1  # position of '\n'
            if prev_line_end < 0 or source[prev_line_end] != "\n":
                break
            prev_line_start = source.rfind("\n", 0, prev_line_end) + 1
            prev_line = source[prev_line_start:prev_line_end]
            stripped = prev_line.strip()
            if not stripped:
                break
            tokens = stripped.split()
            if not all(tok in _MODIFIERS for tok in tokens):
                break
            # Prepend these modifiers in source order.
            modifiers = tokens + modifiers
            cursor = prev_line_start

        return _DefMatch(
            header_start=cursor,
            def_kw_start=def_kw_start,
            def_kw_end=def_kw_end,
            modifiers=modifiers,
        )

    raise DefNotFoundError(f"no top-level `def {def_name}` found in source")


def def_to_abbrev(source: str, def_name: str) -> str:
    """Rewrite ``def <def_name> ...`` as ``abbrev`` (or ``@[reducible] def``).

    - Preserves leading attributes (``@[simp]`` etc.) and doc comments
      (``/-- ... -/``). These are not touched because they live on the lines
      above the modifiers/``def`` keyword.
    - Preserves modifiers: ``noncomputable`` / ``protected`` / ``private`` /
      ``partial`` / ``unsafe``. If ``noncomputable`` or ``partial`` is present,
      ``def`` stays and ``@[reducible]`` is prepended (on its own line, with
      the same indentation as the declaration).
    - Preserves the rest of the declaration verbatim (generics / universe vars
      / binders / body).

    Raises :class:`DefNotFoundError` if no matching top-level ``def`` is found.
    """
    match = _find_def(source, def_name)

    if any(m in _ABBREV_INCOMPATIBLE for m in match.modifiers):
        # Fall back to ``@[reducible] def``: insert attribute on its own line
        # just before the header with matching indentation.
        line_start = source.rfind("\n", 0, match.header_start) + 1
        indent = source[line_start : match.header_start]
        # If the line directly above already has a ``@[reducible]`` attribute,
        # don't duplicate it.
        preceding = source[:line_start]
        if _has_reducible_attr_directly_above(preceding):
            return source
        insertion = f"{indent}@[reducible]\n"
        return source[:line_start] + insertion + source[line_start:]

    # Otherwise replace ``def`` with ``abbrev``.
    return (
        source[: match.def_kw_start]
        + "abbrev"
        + source[match.def_kw_end :]
    )


def remove_redundant_unfolds(source: str, def_name: str) -> str:
    """Remove ``unfold <def_name>`` tactic calls from Lean source.

    Handles three forms:
    - Standalone ``unfold <def_name>`` lines are deleted entirely.
    - ``unfold <def_name>; rest`` standalone lines have the prefix removed; ``rest`` is kept.
    - Inline ``by unfold <def_name>[at loc]; rest`` → ``by rest`` (semicolon-separated).
    - Inline ``by unfold <def_name>[at loc]`` at end of line → ``by``.
    """
    # Match both unqualified (``unfold dist``) and qualified (``unfold Nat.dist``)
    name_pat = rf"(?:\w+\.)*{re.escape(def_name)}"

    # Pass 1: standalone unfold lines (fullmatch on each line)
    standalone_re = re.compile(rf'(\s*)unfold\s+{name_pat}(?:\s*;\s*(.*))?')
    lines = source.splitlines(keepends=True)
    result = []
    for line in lines:
        stripped = line.rstrip('\n')
        eol = line[len(stripped):]
        m = standalone_re.fullmatch(stripped)
        if m:
            indent = m.group(1)
            rest = m.group(2)  # None if no semicolon part
            if rest is not None and rest.strip():
                result.append(indent + rest + eol)
            # else: remove line entirely (standalone unfold or `unfold X;` with no rest)
        else:
            result.append(line)
    source = ''.join(result)

    # Pass 2: inline `by unfold X[at loc]; rest` → `by rest`
    # Handles `by unfold Nat.dist; lia` and `by unfold Nat.dist at h; lia`
    inline_semi_re = re.compile(
        rf'\bby\s+unfold\s+{name_pat}(?:\s+at\s+[\w.]+)?\s*;\s*'
    )
    source = inline_semi_re.sub('by ', source)

    # Pass 3: inline `by unfold X[at loc]` at end of line → `by`
    inline_eol_re = re.compile(
        rf'\bby\s+unfold\s+{name_pat}(?:\s+at\s+[\w.]+)?(?=[ \t]*(?:\n|$))',
        re.MULTILINE,
    )
    source = inline_eol_re.sub('by', source)

    return source


# Matches the start of a new top-level declaration at column 0 (after a newline).
# Used to find the end of a def's block when scanning for termination_by.
_BLOCK_END_RE = re.compile(
    r"\n(?=(?:@\[|/--|"
    r"(?:(?:private|protected|noncomputable|partial|unsafe)\s+)*"
    r"(?:def|abbrev|theorem|lemma|instance|class|structure|inductive"
    r"|section|namespace|end|open|variable|universe)\b))"
)


def has_termination_by(source: str, def_name: str) -> bool:
    """Return True if the named def block contains a ``termination_by`` clause.

    Scopes the search to the block of ``def_name`` only (stops at the next
    top-level declaration). Comment lines are ignored.
    """
    try:
        match = _find_def(source, def_name)
    except DefNotFoundError:
        return False

    rest = source[match.def_kw_start:]
    end_match = _BLOCK_END_RE.search(rest, len("def"))
    block = rest[: end_match.start()] if end_match else rest

    for line in block.splitlines():
        # Strip inline and full-line comments before checking.
        code = re.sub(r"--.*", "", line)
        if re.search(r"\btermination_by\b", code):
            return True
    return False


def _has_reducible_attr_directly_above(prefix: str) -> bool:
    """Return True if the last non-blank line of ``prefix`` is a ``@[reducible]``.

    Only a conservative check — we look at the single line immediately above
    the declaration. A multi-attribute block like ``@[simp, reducible]`` is
    also detected.
    """
    stripped = prefix.rstrip("\n")
    last_nl = stripped.rfind("\n")
    last_line = stripped[last_nl + 1 :].strip()
    if not last_line.startswith("@["):
        return False
    return bool(re.search(r"\breducible\b", last_line))
