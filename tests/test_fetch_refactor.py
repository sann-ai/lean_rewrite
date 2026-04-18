"""Tests for fetch_refactor_commits.py — pure parsing functions only (no git I/O)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from fetch_refactor_commits import (
    extract_def_block,
    extract_all_def_blocks,
    find_changed_def_names,
    find_changed_blocks,
)

# ── find_changed_def_names ────────────────────────────────────────────────────


def test_finds_def_in_added_line():
    diff = """\
--- a/Mathlib/Foo.lean
+++ b/Mathlib/Foo.lean
@@ -1,3 +1,3 @@
-def foo (n : ℕ) : ℕ := n + 1
+def foo (n : ℕ) : ℕ := n
"""
    assert find_changed_def_names(diff) == {"foo"}


def test_finds_structure_name():
    diff = "--- a/A.lean\n+++ b/A.lean\n@@ -1,2 +1,2 @@\n-structure Bar where\n+structure Bar where\n"
    assert find_changed_def_names(diff) == {"Bar"}


def test_finds_class_name():
    diff = "@@ -1 +1 @@\n-class Baz [inst : Foo] where\n"
    assert find_changed_def_names(diff) == {"Baz"}


def test_ignores_header_lines():
    diff = "--- a/foo.lean\n+++ b/foo.lean\n+def realDef : Nat := 0\n"
    assert find_changed_def_names(diff) == {"realDef"}


def test_ignores_indented_def():
    diff = "@@ -1 +1 @@\n+  def inner : Nat := 0\n"
    assert find_changed_def_names(diff) == set()


def test_noncomputable_modifier():
    diff = "@@ -1 +1 @@\n+noncomputable def myDef : ℝ := 0\n"
    assert find_changed_def_names(diff) == {"myDef"}


# ── extract_all_def_blocks ────────────────────────────────────────────────────

MULTI_DEF_SOURCE = """\
def foo (n : ℕ) : ℕ :=
  n + 1

def bar : ℕ := 0

structure MyStruct where
  field : Nat
"""


def test_extract_all_finds_all_defs():
    blocks = extract_all_def_blocks(MULTI_DEF_SOURCE)
    assert set(blocks.keys()) == {"foo", "bar", "MyStruct"}


def test_extract_all_block_contains_body():
    blocks = extract_all_def_blocks(MULTI_DEF_SOURCE)
    assert "n + 1" in blocks["foo"]
    assert "def bar" not in blocks["foo"]


# ── extract_def_block ─────────────────────────────────────────────────────────

SIMPLE_SOURCE = """\
/-- doc comment -/
def foo (n : ℕ) : ℕ :=
  n + 1

def bar : ℕ := 0
"""


def test_extracts_simple_def():
    block = extract_def_block(SIMPLE_SOURCE, "foo")
    assert block is not None
    assert "def foo" in block
    assert "n + 1" in block
    assert "def bar" not in block


def test_extracts_second_def():
    block = extract_def_block(SIMPLE_SOURCE, "bar")
    assert block is not None
    assert "def bar" in block
    assert "def foo" not in block


def test_includes_doc_comment():
    block = extract_def_block(SIMPLE_SOURCE, "foo")
    assert block is not None
    assert "/-- doc comment -/" in block


def test_returns_none_for_missing_def():
    assert extract_def_block(SIMPLE_SOURCE, "nonexistent") is None


def test_no_prefix_match():
    source = "def fooBar : Nat := 0\ndef foo : Nat := 1\n"
    block = extract_def_block(source, "foo")
    assert block is not None
    assert "fooBar" not in block


def test_noncomputable_def():
    source = "noncomputable def myVal : ℝ := 0\n\ndef other : Nat := 1\n"
    block = extract_def_block(source, "myVal")
    assert block is not None
    assert "noncomputable def myVal" in block
    assert "other" not in block


def test_structure_block():
    source = "structure MyStruct where\n  field : Nat\n\ndef foo : Nat := 0\n"
    block = extract_def_block(source, "MyStruct")
    assert block is not None
    assert "structure MyStruct" in block
    assert "field" in block
    assert "def foo" not in block


def test_multiline_body():
    source = (
        "def longDef (a b c : Nat) : Nat :=\n"
        "  let x := a + b\n"
        "  let y := x * c\n"
        "  y\n"
        "\n"
        "def next : Nat := 0\n"
    )
    block = extract_def_block(source, "longDef")
    assert block is not None
    assert "let x" in block
    assert "let y" in block
    assert "def next" not in block


def test_attribute_included():
    source = "@[simp]\ndef helper : Bool := true\n\ndef other : Nat := 0\n"
    block = extract_def_block(source, "helper")
    assert block is not None
    assert "@[simp]" in block


# ── find_changed_blocks ───────────────────────────────────────────────────────


def test_single_changed_block():
    before = "def foo : Nat := 0\ndef bar : Nat := 1\n"
    after = "def foo : Nat := 42\ndef bar : Nat := 1\n"
    changed = find_changed_blocks(before, after)
    assert len(changed) == 1
    name, b, a = changed[0]
    assert name == "foo"
    assert "42" in a
    assert "0" in b


def test_no_changed_block():
    src = "def foo : Nat := 0\n"
    changed = find_changed_blocks(src, src)
    assert changed == []


def test_two_changed_blocks():
    before = "def foo : Nat := 0\ndef bar : Nat := 1\n"
    after = "def foo : Nat := 2\ndef bar : Nat := 3\n"
    changed = find_changed_blocks(before, after)
    assert len(changed) == 2


def test_new_def_not_reported():
    before = "def foo : Nat := 0\n"
    after = "def foo : Nat := 0\ndef bar : Nat := 1\n"
    changed = find_changed_blocks(before, after)
    assert changed == []  # bar is new, not a change to existing block


def test_body_only_change_detected():
    before = "def foo (n : Nat) : Nat :=\n  n + 1\n\ndef bar : Nat := 0\n"
    after = "def foo (n : Nat) : Nat :=\n  n\n\ndef bar : Nat := 0\n"
    changed = find_changed_blocks(before, after)
    assert len(changed) == 1
    assert changed[0][0] == "foo"
