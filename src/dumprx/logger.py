"""Structured debug logging with loguru: rich stderr sink + rotating file sink."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from loguru import logger

_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan> | <level>{message}</level>"
)


class _InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame = logging.currentframe()
        depth = 2
        while frame and (
            frame.f_code.co_filename == logging.__file__
            or "sebaubuntu_libs" in frame.f_code.co_filename
        ):
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def bootstrap(
    *,
    level: str = "DEBUG",
    log_file: Path | None = None,
    console: bool = True,
    file_retention: int = 3,
    file_size: str = "1 MB",
) -> None:
    """Install sinks. Safe to call repeatedly; previous sinks are removed."""
    logger.remove()
    logging.basicConfig(handlers=[_InterceptHandler()], level=logging.DEBUG, force=True)
    if console:
        from rich.console import Console

        Console(stderr=True, force_terminal=True)
        logger.add(sys.stderr, level=level, format=_FORMAT, enqueue=True)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            str(log_file),
            level=level,
            rotation=file_size,
            retention=file_retention,
            enqueue=True,
            backtrace=False,
            diagnose=False,
        )


__all__ = ["bootstrap", "logger"]
