"""Tests for fetch_refactor_commits_post_module.py — pure logic, no git I/O."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from fetch_refactor_commits_post_module import (
    MODULE_SYSTEM_SHA,
    get_candidate_shas_after,
    is_def_to_abbrev_change,
    _get_def_keyword,
    process_commit,
)


# ── _get_def_keyword ──────────────────────────────────────────────────────────


def test_keyword_plain_def():
    block = "def foo : Nat := 0\n"
    assert _get_def_keyword(block) == "def"


def test_keyword_abbrev():
    block = "abbrev foo : Nat := 0\n"
    assert _get_def_keyword(block) == "abbrev"


def test_keyword_noncomputable_def():
    block = "noncomputable def myVal : ℝ := 0\n"
    assert _get_def_keyword(block) == "def"


def test_keyword_with_attribute():
    block = "@[simp]\ndef helper : Bool := true\n"
    assert _get_def_keyword(block) == "def"


def test_keyword_none_for_non_def():
    block = "theorem foo : 1 = 1 := rfl\n"
    assert _get_def_keyword(block) is None


# ── is_def_to_abbrev_change ───────────────────────────────────────────────────


def test_def_to_abbrev():
    before = "def foo : Nat := 0\n"
    after = "abbrev foo : Nat := 0\n"
    assert is_def_to_abbrev_change(before, after) is True


def test_abbrev_to_def():
    before = "abbrev foo : Nat := 0\n"
    after = "def foo : Nat := 0\n"
    assert is_def_to_abbrev_change(before, after) is True


def test_def_to_def_is_not_abbrev_change():
    before = "def foo : Nat := 0\n"
    after = "def foo : Nat := 1\n"
    assert is_def_to_abbrev_change(before, after) is False


def test_abbrev_to_abbrev_is_not_abbrev_change():
    before = "abbrev foo : Nat := 0\n"
    after = "abbrev foo : Nat := 1\n"
    assert is_def_to_abbrev_change(before, after) is False


def test_noncomputable_def_to_abbrev():
    before = "noncomputable def myVal : ℝ := 0\n"
    after = "abbrev myVal : ℝ := 0\n"
    assert is_def_to_abbrev_change(before, after) is True


def test_attribute_preserved_in_abbrev_change():
    before = "@[simp]\ndef helper : Bool := true\n"
    after = "@[simp]\nabbrev helper : Bool := true\n"
    assert is_def_to_abbrev_change(before, after) is True


# ── get_candidate_shas_after (SHA filter) ─────────────────────────────────────


def test_sha_filter_returns_refactor_perf_chore_commits():
    mock_output = (
        "aabbcc1111111111111111111111111111111111\trefactor(Foo): simplify\n"
        "bbccdd2222222222222222222222222222222222\tfeat(Bar): add lemma\n"
        "ccddee3333333333333333333333333333333333\tperf(Baz): speedup\n"
        "ddeeff4444444444444444444444444444444444\tchore(Qux): make it an abbrev\n"
    )
    with patch(
        "fetch_refactor_commits_post_module._git", return_value=mock_output
    ) as mock_git:
        result = get_candidate_shas_after(Path("/fake/mathlib"), "deadbeef")
        # Should return refactor, perf, and chore commits — not feat
        assert len(result) == 3
        shas = [r[0] for r in result]
        assert "aabbcc1111111111111111111111111111111111" in shas
        assert "ccddee3333333333333333333333333333333333" in shas
        assert "ddeeff4444444444444444444444444444444444" in shas
        assert "bbccdd2222222222222222222222222222222222" not in shas
        # Verify git was called with the correct after-SHA range
        call_args = mock_git.call_args
        assert "deadbeef..HEAD" in call_args[0]


def test_sha_filter_uses_range_syntax():
    """get_candidate_shas_after must use '<sha>..HEAD' syntax to bound the scan."""
    with patch(
        "fetch_refactor_commits_post_module._git", return_value=""
    ) as mock_git:
        get_candidate_shas_after(Path("/fake/mathlib"), "abc123")
        call_args = mock_git.call_args[0]
        assert "abc123..HEAD" in call_args


def test_sha_filter_empty_log():
    with patch("fetch_refactor_commits_post_module._git", return_value=""):
        result = get_candidate_shas_after(Path("/fake/mathlib"), "abc123")
        assert result == []


def test_default_after_sha_is_module_system():
    assert MODULE_SYSTEM_SHA == "6a54a80825"


# ── process_commit ────────────────────────────────────────────────────────────


def test_process_commit_returns_record_for_def_to_abbrev():
    before_src = "def foo : Nat := 0\ndef bar : Nat := 1\n"
    after_src = "abbrev foo : Nat := 0\ndef bar : Nat := 1\n"
    with (
        patch(
            "fetch_refactor_commits_post_module.get_changed_lean_files",
            return_value=["Mathlib/Test.lean"],
        ),
        patch(
            "fetch_refactor_commits_post_module.get_file_at",
            side_effect=[before_src, after_src],
        ),
    ):
        rec = process_commit("sha1", "refactor: foo", Path("/mathlib"))
        assert rec is not None
        assert rec["def_name"] == "foo"
        assert rec["before_def"].startswith("def foo")
        assert rec["after_def"].startswith("abbrev foo")


def test_process_commit_skips_multi_file_commit():
    with patch(
        "fetch_refactor_commits_post_module.get_changed_lean_files",
        return_value=["A.lean", "B.lean"],
    ):
        assert process_commit("sha1", "refactor: multi", Path("/mathlib")) is None


def test_process_commit_skips_non_abbrev_change():
    before_src = "def foo : Nat := 0\n"
    after_src = "def foo : Nat := 1\n"
    with (
        patch(
            "fetch_refactor_commits_post_module.get_changed_lean_files",
            return_value=["Mathlib/Test.lean"],
        ),
        patch(
            "fetch_refactor_commits_post_module.get_file_at",
            side_effect=[before_src, after_src],
        ),
    ):
        assert process_commit("sha1", "refactor: body change", Path("/mathlib")) is None


def test_process_commit_skips_two_abbrev_block_changes():
    # Two blocks both change def→abbrev: ambiguous, should be skipped
    before_src = "def foo : Nat := 0\ndef bar : Nat := 1\n"
    after_src = "abbrev foo : Nat := 0\nabbrev bar : Nat := 1\n"
    with (
        patch(
            "fetch_refactor_commits_post_module.get_changed_lean_files",
            return_value=["Mathlib/Test.lean"],
        ),
        patch(
            "fetch_refactor_commits_post_module.get_file_at",
            side_effect=[before_src, after_src],
        ),
    ):
        assert process_commit("sha1", "refactor: two blocks", Path("/mathlib")) is None


def test_process_commit_accepts_abbrev_change_with_other_block_changes():
    # One def→abbrev change plus an unrelated body change — should be accepted
    before_src = "def foo : Nat := 0\ndef bar : Nat := 1\n"
    after_src = "abbrev foo : Nat := 0\ndef bar : Nat := 42\n"
    with (
        patch(
            "fetch_refactor_commits_post_module.get_changed_lean_files",
            return_value=["Mathlib/Test.lean"],
        ),
        patch(
            "fetch_refactor_commits_post_module.get_file_at",
            side_effect=[before_src, after_src],
        ),
    ):
        rec = process_commit("sha1", "chore: make foo an abbrev", Path("/mathlib"))
        assert rec is not None
        assert rec["def_name"] == "foo"
