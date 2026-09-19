"""Extractor registry: ordered, first-match-wins classification.

Plug-and-play seam of the pipeline. Each format module registers an
`Extractor` subclass with `@extractor(order, kind)`. Containers sort ahead of
terminals regardless of order number (dumper.sh evaluates all container
checks before the terminal chain).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from dumprx.arch import Archive
from dumprx.config import Config


class ClassifyError(RuntimeError):
    """Raised when no registered extractor detects the source."""


class ExtractChainError(RuntimeError):
    """Fatal problem while running the extraction chain."""


class StageLimitError(ExtractChainError):
    """Containers kept re-queueing past the safety hop limit."""


@dataclass
class WorkContext:
    """Shared context passed to every extractor: source + origin + dirs."""

    source: Path
    outdir: Path
    workdir: Path
    config: Config
    origin_archive: Path | None = None
    archive_listing: Archive | None = None

    @property
    def inputdir(self) -> Path:
        return self.config.paths.inputdir

    @property
    def tools(self):
        from dumprx.tools import Tools

        return Tools(utilsdir=self.config.paths.utilsdir)


class Extractor(ABC):
    """Base class for firmware format extractors.

    - kind "container": decodes a wrapper, `extract()` returns the next
      source `Path` (file or directory) for the stage queue, or None.
    - kind "terminal": produces partition images in the work dir.
    """

    order: int = 1_000_000
    kind: str = "terminal"
    name: str = "unknown"

    @abstractmethod
    def detect(self, ctx: WorkContext) -> bool:
        """True when this extractor owns the source."""

    def extract(self, ctx: WorkContext) -> Path | None:
        """Run extraction. Containers return the next source; terminals None."""
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{self.name} order={self.order} kind={self.kind}>"


_REGISTRY: list[Extractor] = []


def extractor(order: int, kind: str):
    """Class decorator registering an Extractor subclass into the registry."""

    def deco(cls: type[Extractor]) -> type[Extractor]:
        instance = cls()
        instance.order = order
        instance.kind = kind
        if instance.name == "unknown":
            instance.name = cls.__name__.lower()
        _REGISTRY.append(instance)
        logger.debug("extractor registered: {}", instance)
        return cls

    return deco


def load_extractors() -> list[Extractor]:
    """Import every extractor submodule so registrations take effect."""
    import importlib
    import pkgutil

    package_name, _ = __name__.rsplit(".", 1)
    package = importlib.import_module(package_name)
    for module in pkgutil.iter_modules(package.__path__):
        if module.name in ("base",):
            continue
        try:
            importlib.import_module(f"{package_name}.{module.name}")
        except Exception as exc:  # noqa: BLE001 - a broken format must not kill all
            logger.error("failed to load extractor module {}: {}", module.name, exc)
    return list(_REGISTRY)


def ordered() -> list[Extractor]:
    return sorted(_REGISTRY, key=lambda e: (0 if e.kind == "container" else 1, e.order))


_LOADED = False


def _ensure_loaded() -> None:
    """Register every extractor submodule once before first classification."""
    global _LOADED
    if not _LOADED:
        load_extractors()
        _LOADED = True


def classify(ctx: WorkContext) -> Extractor:
    """First registered extractor whose detect() succeeds (containers first)."""
    _ensure_loaded()
    for extractor_ in ordered():
        try:
            if extractor_.detect(ctx):
                logger.debug("classified {} as {}", ctx.source.name, extractor_.name)
                return extractor_
        except Exception as exc:  # noqa: BLE001 - a bad detect must not abort
            logger.error("detect {} raised for {}: {}", extractor_.name, ctx.source, exc)
    attempted = ", ".join(e.name for e in ordered())
    raise ClassifyError(
        f"no extractor matched {ctx.source} (source kind {_kind(ctx)}). "
        f"Candidates evaluated in order (first match wins): {attempted}"
    )


def _kind(ctx: WorkContext) -> str:
    try:

        tools = ctx.tools
        zz = tools.seven_zz
        from dumprx.process import run

        res = run([zz, "l", "-ba", str(ctx.source)], capture=True, timeout=60)
        return f"archive({res.returncode})" if ctx.source.is_file() else "directory"
    except Exception as exc:  # noqa: BLE001
        return f"unreadable({exc})"


def base_extractor_instance() -> Any:
    return None


__all__ = ["ClassifyError", "ExtractChainError", "Extractor", "StageLimitError", "WorkContext", "classify", "extractor", "load_extractors", "ordered"]
