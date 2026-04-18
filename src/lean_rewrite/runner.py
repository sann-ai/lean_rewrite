"""Subprocess wrapper around `lake build <module>` for a mathlib worktree.

Used by the evaluator and the end-to-end pipeline to drive Lean builds and
capture structured results (stdout, stderr, exit code, wall time, timeout).
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


class LakeNotFoundError(FileNotFoundError):
    """Raised when the ``lake`` executable cannot be invoked."""


class WorktreeNotFoundError(FileNotFoundError):
    """Raised when the supplied mathlib worktree path does not exist."""


@dataclass(frozen=True)
class BuildResult:
    """Structured result of a single ``lake build`` invocation."""

    module: str
    worktree: Path
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    wall_time_sec: float
    timed_out: bool

    @property
    def success(self) -> bool:
        """True when the build exited cleanly (no timeout, zero exit)."""
        return not self.timed_out and self.returncode == 0


def run_lake_build(
    worktree: str | Path,
    module: str,
    *,
    timeout: float | None = None,
    lake: str = "lake",
    extra_args: tuple[str, ...] = (),
) -> BuildResult:
    """Run ``lake build <module>`` in ``worktree`` and capture its result.

    Parameters
    ----------
    worktree:
        Path to a mathlib (or any Lake project) working tree. Must contain a
        ``lakefile.lean`` / ``lakefile.toml``.
    module:
        Lean module name to build, e.g. ``"Mathlib.Logic.Basic"``.
    timeout:
        Wall-clock timeout in seconds. If the child exceeds it, it is killed
        and ``BuildResult.timed_out`` is ``True``. ``None`` means no timeout.
    lake:
        Name or absolute path of the ``lake`` binary. Defaults to ``"lake"``
        (resolved via ``PATH``).
    extra_args:
        Additional arguments appended after ``module``. Useful for flags like
        ``("--no-cache",)``.

    Returns
    -------
    BuildResult
        Structured outcome. Never raises on build failure — the caller inspects
        ``returncode`` / ``success`` / ``timed_out``.

    Raises
    ------
    WorktreeNotFoundError
        If ``worktree`` does not exist or is not a directory.
    LakeNotFoundError
        If the ``lake`` executable cannot be found / executed.
    """
    wt = Path(worktree)
    if not wt.is_dir():
        raise WorktreeNotFoundError(f"mathlib worktree not found: {wt}")

    cmd: tuple[str, ...] = (lake, "build", module, *extra_args)
    start = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(wt),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        stdout = proc.stdout
        stderr = proc.stderr
        returncode = proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        # POSIX convention for timeout / SIGKILL-ish exits.
        returncode = -1
    except FileNotFoundError as exc:
        raise LakeNotFoundError(
            f"could not execute {lake!r}: {exc}"
        ) from exc
    wall = time.monotonic() - start

    return BuildResult(
        module=module,
        worktree=wt,
        command=cmd,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        wall_time_sec=wall,
        timed_out=timed_out,
    )
