"""Single subprocess runner: timeout, bounded output, structured debug logging."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass

from loguru import logger


class ProcessError(RuntimeError):
    """Raised when a command exits non-zero and check=True."""


class ProcessTimeout(RuntimeError):
    """Raised when a command exceeds the timeout."""


@dataclass(frozen=True)
class Result:
    argv: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: bytes
    elapsed_ms: int

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def stdout_text(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")


def which(name: str) -> str | None:
    return shutil.which(name)


def run(
    argv: Sequence[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    timeout: float = 3600,
    capture: bool = False,
    check: bool = False,
    extra_env: dict[str, str] | None = None,
    input_data: bytes | None = None,
) -> Result:
    """Run a command once. Always logs argv / cwd / retcode / elapsed at DEBUG.

    - `capture=False`: stdout+stderr discarded (DEVNULL), like `>/dev/null 2>&1`.
    - `capture=True`: both streams captured, never left unread (no pipe deadlock).
    """
    started = time.monotonic()
    stdout: int | None
    stderr: int | None
    if capture:
        stdout = stderr = subprocess.PIPE
    else:
        stdout = stderr = subprocess.DEVNULL
    env = None
    if extra_env:
        env = os.environ.copy()
        env.update(extra_env)
    try:
        proc = subprocess.run(
            list(argv),
            cwd=cwd,
            stdout=stdout,
            stderr=stderr,
            input=input_data,
            env=env,
            timeout=timeout,
        )
    except FileNotFoundError:
        logger.error("exec not found: {}", argv[0])
        raise ProcessError(f"command not found: {argv[0]}") from None
    except subprocess.TimeoutExpired as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        logger.error(
            "timeout after {}ms: cmd={!r} cwd={} timeout={}s",
            elapsed,
            list(argv),
            str(cwd or os.getcwd()),
            timeout,
        )
        raise ProcessTimeout(
            f"command timed out after {timeout}s: {' '.join(map(str, argv))}"
        ) from exc
    elapsed = int((time.monotonic() - started) * 1000)
    result = Result(
        argv=tuple(argv),
        returncode=proc.returncode,
        stdout=proc.stdout or b"",
        stderr=proc.stderr or b"",
        elapsed_ms=elapsed,
    )
    logger.debug(
        "cmd={!r} cwd={} retcode={} elapsed_ms={}",
        list(argv),
        str(cwd or os.getcwd()),
        proc.returncode,
        elapsed,
    )
    if check and proc.returncode != 0:
        raise ProcessError(
            f"command failed ({proc.returncode}): {' '.join(map(str, argv))}"
        )
    return result


__all__ = ["ProcessError", "ProcessTimeout", "Result", "run", "which"]
