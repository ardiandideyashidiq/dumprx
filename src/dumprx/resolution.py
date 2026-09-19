"""Input source resolution: folder-of-archive vs extracted-firmware folder.

Ports dumper.sh's input normalization (lines ~278-363): a supplied directory
is either re-loaded as its single supported archive (or aborts on multiples),
copied wholesale into the work dir when it looks like an already-extracted
firmware, or rejected as unsupported.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from dumprx.config import Config


class ResolutionError(RuntimeError):
    """Input cannot be turned into a dumpable source."""


ARCHIVE_SUFFIXES = (".tar", ".zip", ".rar", ".7z")

# markers for an already-extracted firmware folder (bash grep alternation)
FIRMWARE_MARKERS = (
    "system.ext4.tar",
    "system.new.dat",
    "system_new.img",
    "system.img",
    "system-sign.img",
    "system.bin",
    "payload.bin",
    "rawprogram",
    "system.sin",
    "system_",
    "system-p",
    "super",
    "UPDATE.APP",
    ".pac",
    ".nb0",
)


@dataclass(frozen=True)
class ResolvedSource:
    kind: str  # "file" | "archive" | "workdir"
    path: Path | None = None  # the archive/file for kind file/archive


def resolve_source(source: Path, config: Config) -> ResolvedSource:
    """Normalize `source`. May copy files into the work dir."""
    if source.is_file():
        return ResolvedSource("file", source.resolve())

    archives = _archives_in(source)
    if archives:
        if len(archives) > 1:
            raise ResolutionError(
                f"More Than One Archive File Is Available In {source} folder. "
                "Please Use Direct Archive Path Along With This Toolkit"
            )
        chosen = archives[0]
        logger.info("Folder has one archive; re-sourcing {}", chosen)
        return ResolvedSource("archive", chosen)

    top_files = [p for p in source.iterdir() if p.is_file()]
    if any(_marker_hit(p.name) for p in top_files):
        workdir = config.paths.workdir
        workdir.mkdir(parents=True, exist_ok=True)
        from dumprx.process import run

        for p in top_files:
            run(["cp", "-a", str(p), str(workdir / p.name)], timeout=600)
        logger.info("Copying everything into {} for further operations", workdir)
        return ResolvedSource("workdir", workdir)

    raise ResolutionError(
        f"This type of firmware is not supported: {source} (no archive, no firmware markers)"
    )


def _archives_in(source: Path) -> list[Path]:
    out: list[Path] = []
    for p in source.iterdir():
        if p.is_file() and p.name != "compatibility.zip" and p.suffix.lower() in ARCHIVE_SUFFIXES:
            out.append(p.resolve())
    return sorted(out)


def _marker_hit(name: str) -> bool:
    lower = name.lower()
    return any(m in lower for m in FIRMWARE_MARKERS)


__all__ = ["ResolutionError", "ResolvedSource", "resolve_source"]
