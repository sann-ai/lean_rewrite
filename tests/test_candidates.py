"""Tests for ``lean_rewrite.candidates.def_to_abbrev`` and ``remove_redundant_unfolds``."""

from __future__ import annotations

import pytest

from lean_rewrite.candidates import DefNotFoundError, def_to_abbrev, remove_redundant_unfolds


def test_basic_def_to_abbrev() -> None:
    src = "def foo (x : Nat) : Nat := x + 1\n"
    out = def_to_abbrev(src, "foo")
    assert out == "abbrev foo (x : Nat) : Nat := x + 1\n"


def test_preserves_body_exactly() -> None:
    src = "def foo : Nat :=\n  let y := 3\n  y + y\n"
    out = def_to_abbrev(src, "foo")
    assert out == "abbrev foo : Nat :=\n  let y := 3\n  y + y\n"


def test_preserves_attribute_above() -> None:
    src = "@[simp]\ndef foo (x : Nat) : Nat := x\n"
    out = def_to_abbrev(src, "foo")
    assert out == "@[simp]\nabbrev foo (x : Nat) : Nat := x\n"


def test_preserves_multiple_attributes() -> None:
    src = "@[simp, grind =]\ndef foo : Nat := 0\n"
    out = def_to_abbrev(src, "foo")
    assert out == "@[simp, grind =]\nabbrev foo : Nat := 0\n"


def test_preserves_doc_comment() -> None:
    src = "/-- The `foo` function returns its input plus one. -/\ndef foo (x : Nat) := x + 1\n"
    out = def_to_abbrev(src, "foo")
    assert out == (
        "/-- The `foo` function returns its input plus one. -/\n"
        "abbrev foo (x : Nat) := x + 1\n"
    )


def test_preserves_doc_comment_and_attribute() -> None:
    src = (
        "/-- Returns `x + 1`. -/\n"
        "@[simp]\n"
        "def foo (x : Nat) := x + 1\n"
    )
    out = def_to_abbrev(src, "foo")
    assert out == (
        "/-- Returns `x + 1`. -/\n"
        "@[simp]\n"
        "abbrev foo (x : Nat) := x + 1\n"
    )


def test_protected_modifier() -> None:
    src = "protected def foo (x : Nat) := x\n"
    out = def_to_abbrev(src, "foo")
    assert out == "protected abbrev foo (x : Nat) := x\n"


def test_private_modifier() -> None:
    src = "private def foo (x : Nat) := x\n"
    out = def_to_abbrev(src, "foo")
    assert out == "private abbrev foo (x : Nat) := x\n"


def test_noncomputable_falls_back_to_reducible() -> None:
    src = "noncomputable def foo : Nat := Classical.choice ⟨0⟩\n"
    out = def_to_abbrev(src, "foo")
    # `abbrev` is incompatible with `noncomputable`, so we add `@[reducible]`
    # on its own line and leave the original declaration intact.
    assert out == (
        "@[reducible]\n"
        "noncomputable def foo : Nat := Classical.choice ⟨0⟩\n"
    )


def test_partial_falls_back_to_reducible() -> None:
    src = "partial def foo : Nat → Nat\n  | 0 => 0\n  | n + 1 => foo n\n"
    out = def_to_abbrev(src, "foo")
    assert out == (
        "@[reducible]\n"
        "partial def foo : Nat → Nat\n  | 0 => 0\n  | n + 1 => foo n\n"
    )


def test_reducible_not_duplicated() -> None:
    src = (
        "@[reducible]\n"
        "noncomputable def foo : Nat := Classical.choice ⟨0⟩\n"
    )
    out = def_to_abbrev(src, "foo")
    # Already has `@[reducible]`; don't add another one.
    assert out == src


def test_generic_type_param_preserved() -> None:
    src = "def foo {α : Type} (x : α) : α := x\n"
    out = def_to_abbrev(src, "foo")
    assert out == "abbrev foo {α : Type} (x : α) : α := x\n"


def test_universe_variable_preserved() -> None:
    src = "def foo.{u} {α : Type u} (x : α) : α := x\n"
    out = def_to_abbrev(src, "foo")
    assert out == "abbrev foo.{u} {α : Type u} (x : α) : α := x\n"


def test_sort_universe_preserved() -> None:
    src = "def hidden {α : Sort*} {a : α} : α := a\n"
    out = def_to_abbrev(src, "hidden")
    assert out == "abbrev hidden {α : Sort*} {a : α} : α := a\n"


def test_multiline_definition() -> None:
    src = (
        "def Function.swap₂ {ι₁ ι₂ : Sort*} {κ₁ : ι₁ → Sort*} {κ₂ : ι₂ → Sort*}\n"
        "    (f : ∀ i₁ i₂, κ₁ i₁ → κ₂ i₂) (a₁ : ι₁) (a₂ : ι₂) :\n"
        "    κ₁ a₁ → κ₂ a₂ → _ :=\n"
        "  fun x y => f a₁ a₂ x y\n"
    )
    out = def_to_abbrev(src, "Function.swap₂")
    assert out == (
        "abbrev Function.swap₂ {ι₁ ι₂ : Sort*} {κ₁ : ι₁ → Sort*} {κ₂ : ι₂ → Sort*}\n"
        "    (f : ∀ i₁ i₂, κ₁ i₁ → κ₂ i₂) (a₁ : ι₁) (a₂ : ι₂) :\n"
        "    κ₁ a₁ → κ₂ a₂ → _ :=\n"
        "  fun x y => f a₁ a₂ x y\n"
    )


def test_missing_def_raises() -> None:
    src = "def foo : Nat := 0\n"
    with pytest.raises(DefNotFoundError):
        def_to_abbrev(src, "bar")


def test_does_not_match_prefix_of_other_def() -> None:
    src = "def fooBar : Nat := 0\ndef foo : Nat := 1\n"
    out = def_to_abbrev(src, "foo")
    # Only the exact ``foo`` should be rewritten, not ``fooBar``.
    assert out == "def fooBar : Nat := 0\nabbrev foo : Nat := 1\n"


def test_does_not_match_inside_comment_or_string() -> None:
    # A ``def foo`` appearing inside a comment line should not be matched,
    # because that "line" begins with ``--``, not ``def``.
    src = "-- def foo : Nat := 0\ndef foo : Nat := 1\n"
    out = def_to_abbrev(src, "foo")
    assert out == "-- def foo : Nat := 0\nabbrev foo : Nat := 1\n"


def test_first_occurrence_when_ambiguous() -> None:
    # If two top-level defs have the same name (unusual but possible across
    # namespaces / sections), rewrite only the first match and leave the rest.
    src = "def foo : Nat := 0\ndef foo : Nat := 1\n"
    out = def_to_abbrev(src, "foo")
    assert out == "abbrev foo : Nat := 0\ndef foo : Nat := 1\n"


def test_protected_noncomputable_combination() -> None:
    src = "protected noncomputable def foo : Nat := Classical.choice ⟨0⟩\n"
    out = def_to_abbrev(src, "foo")
    assert out == (
        "@[reducible]\n"
        "protected noncomputable def foo : Nat := Classical.choice ⟨0⟩\n"
    )


def test_indented_declaration_keeps_indent() -> None:
    # Inside a ``namespace`` block mathlib often does not indent, but Lean
    # allows it. Verify that indentation is preserved on the inserted
    # ``@[reducible]`` line.
    src = "  noncomputable def foo : Nat := 0\n"
    out = def_to_abbrev(src, "foo")
    assert out == (
        "  @[reducible]\n"
        "  noncomputable def foo : Nat := 0\n"
    )


# ---------------------------------------------------------------------------
# remove_redundant_unfolds
# ---------------------------------------------------------------------------

def test_remove_standalone_unfold_line() -> None:
    src = "theorem bar : True := by\n  unfold Nat.dist\n  trivial\n"
    out = remove_redundant_unfolds(src, "Nat.dist")
    assert out == "theorem bar : True := by\n  trivial\n"
    assert "unfold Nat.dist" not in out


def test_remove_unfold_with_trailing_semicolon_only() -> None:
    src = "theorem bar : True := by\n  unfold Nat.dist;\n  trivial\n"
    out = remove_redundant_unfolds(src, "Nat.dist")
    assert "unfold Nat.dist" not in out
    assert "trivial" in out


def test_remove_unfold_semicolon_rest_preserved() -> None:
    src = "theorem bar : True := by\n  unfold Nat.dist; ring\n"
    out = remove_redundant_unfolds(src, "Nat.dist")
    assert "unfold Nat.dist" not in out
    assert "ring" in out
    # indent must be preserved
    assert "  ring" in out


def test_remove_multiple_unfold_lines() -> None:
    src = (
        "theorem a : True := by\n"
        "  unfold Nat.dist\n"
        "  trivial\n"
        "theorem b : True := by\n"
        "  unfold Nat.dist\n"
        "  trivial\n"
    )
    out = remove_redundant_unfolds(src, "Nat.dist")
    assert out.count("unfold Nat.dist") == 0


def test_remove_unfold_indented() -> None:
    src = "    unfold Nat.dist\n"
    out = remove_redundant_unfolds(src, "Nat.dist")
    assert out == ""


def test_does_not_touch_other_def_unfolds() -> None:
    src = "theorem bar : True := by\n  unfold Nat.dist\n  unfold Nat.other\n  trivial\n"
    out = remove_redundant_unfolds(src, "Nat.dist")
    assert "unfold Nat.dist" not in out
    assert "unfold Nat.other" in out


def test_does_not_touch_unfold_with_longer_name() -> None:
    # unfold Nat.distance should NOT be removed when def_name is "Nat.dist"
    src = "  unfold Nat.distance\n"
    out = remove_redundant_unfolds(src, "Nat.dist")
    assert out == src


def test_nat_dist_example_removes_all_unfolds() -> None:
    # Realistic Nat.dist scenario: 16 unfold calls should all be removed
    src = "theorem t : True := by\n" + "  unfold Nat.dist\n" * 16 + "  trivial\n"
    out = remove_redundant_unfolds(src, "Nat.dist")
    assert "unfold Nat.dist" not in out
    assert "trivial" in out


def test_remove_unfold_unqualified_def_name_matches_qualified_usage() -> None:
    # Pipeline passes unqualified name ("dist") but source uses "unfold Nat.dist"
    src = "theorem foo : True := by\n  unfold Nat.dist; lia\n"
    out = remove_redundant_unfolds(src, "dist")
    assert "unfold Nat.dist" not in out
    assert "lia" in out


def test_remove_unfold_unqualified_does_not_partial_match() -> None:
    # "dist" should not remove "unfold Nat.distance"
    src = "  unfold Nat.distance\n"
    out = remove_redundant_unfolds(src, "dist")
    assert out == src
