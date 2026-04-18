"""Tests for lean_rewrite.runner.

The happy-path test shells out to a real mathlib4 worktree at
``/Users/san/mathlib4`` and expects a pre-warmed cache (see ``T001``). It is
skipped automatically when the worktree or ``lake`` is unavailable so the
suite still runs on machines without the Lean toolchain.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from lean_rewrite.runner import (
    BuildResult,
    LakeNotFoundError,
    WorktreeNotFoundError,
    run_lake_build,
)

MATHLIB = Path("/Users/san/mathlib4")
_HAS_LAKE = shutil.which("lake") is not None
_HAS_MATHLIB = MATHLIB.is_dir()

requires_lean = pytest.mark.skipif(
    not (_HAS_LAKE and _HAS_MATHLIB),
    reason="requires lake on PATH and mathlib4 at /Users/san/mathlib4",
)


@requires_lean
def test_build_cached_module_succeeds() -> None:
    """Mathlib.Logic.Basic builds cleanly against the cached mathlib."""
    result = run_lake_build(MATHLIB, "Mathlib.Logic.Basic", timeout=120)

    assert isinstance(result, BuildResult)
    assert result.success, (
        f"build failed: rc={result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert result.returncode == 0
    assert result.timed_out is False
    assert result.module == "Mathlib.Logic.Basic"
    assert result.worktree == MATHLIB
    assert result.command[:3] == ("lake", "build", "Mathlib.Logic.Basic")
    assert result.wall_time_sec > 0
    # With the mathlib cache in place, Mathlib.Logic.Basic builds in well under
    # a minute. If this ever regresses the whole runner story is moot, so the
    # bound is intentionally loose.
    assert result.wall_time_sec < 120


@requires_lean
def test_build_nonexistent_module_fails() -> None:
    """A bogus module name produces a non-zero exit and captured diagnostics."""
    result = run_lake_build(
        MATHLIB,
        "Mathlib.ThisModuleDoesNotExist_lean_rewrite_test",
        timeout=120,
    )

    assert not result.success
    assert result.returncode != 0
    assert result.timed_out is False
    # lake reports unknown modules on stderr (occasionally stdout depending on
    # version); we just need *some* diagnostic text somewhere.
    combined = result.stdout + result.stderr
    assert combined.strip(), "expected lake to emit a diagnostic for unknown module"


def test_missing_worktree_raises(tmp_path: Path) -> None:
    """Non-existent worktree fails fast with a typed error, before spawning lake."""
    missing = tmp_path / "definitely-not-a-worktree"
    with pytest.raises(WorktreeNotFoundError):
        run_lake_build(missing, "Mathlib.Logic.Basic")


def test_missing_lake_binary_raises(tmp_path: Path) -> None:
    """A bogus ``lake`` path surfaces as ``LakeNotFoundError``."""
    with pytest.raises(LakeNotFoundError):
        run_lake_build(
            tmp_path,
            "Whatever",
            lake=str(tmp_path / "no-such-lake-binary"),
        )
