"""Extraction pipeline: stage-queue dispatch, partition promote, finalize.

Replaces the bash `reload_and_rerun` recursion: containers push a `next_source`
back onto the queue and the loop re-classifies; the first terminal breaks the
chain (terminals consume the whole input). Afterward partitions are promoted
out of the work dir, filesystem trees are extracted, and all_files.txt etc.
are generated inside OUTDIR.
"""

from __future__ import annotations

import atexit
import os
import shutil
import signal
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from dumprx.arch import Archive
from dumprx.config import EXT4_PARTITIONS, OTHER_PARTITIONS, PARTITIONS
from dumprx.extractors import WorkContext, classify
from dumprx.extractors.base import ExtractChainError, StageLimitError
from dumprx.images import strip_signed_header, to_raw_image
from dumprx.partitions import (
    extract_euclid_imgs,
    extract_fs_partitions,
)


@dataclass
class PipelineResult:
    outdir: Path
    terminal: str
    partitions: list[str]
    extracted_trees: dict[str, bool] = field(default_factory=dict)


def prepare_listing(ctx: WorkContext) -> WorkContext:
    """Attach a file-backed 7zz listing when the source is an archive file."""
    if ctx.archive_listing is not None or not ctx.source.is_file():
        return ctx
    listing_file = ctx.workdir / f"archive_listing_{ctx.source.stat().st_mtime_ns}.txt"
    ctx.archive_listing = Archive(ctx.source, listing_file).write_listing(
        ctx.tools.seven_zz
    ) if _seven_zz_available(ctx) else None
    if ctx.archive_listing is None:
        raise ExtractChainError(f"cannot list archive {ctx.source}")
    return ctx


def _seven_zz_available(ctx: WorkContext) -> bool:
    zz = ctx.tools.seven_zz
    return bool(zz) and (zz == "7zz" or Path(zz).exists() or shutil.which(zz))


def extract_chain(ctx: WorkContext) -> str:
    """Run containers until a terminal consumes the input; return its name."""
    hops = 0
    while True:
        hops += 1
        if hops > 40:
            raise StageLimitError(f"extractor re-queue loop: {hops} hops")
        prepare_listing(ctx)
        terminal = classify(ctx)
        logger.info("stage {}: {} on {}", hops, terminal.name, ctx.source)
        next_source = terminal.extract(ctx)
        if next_source is None:
            return terminal.name
        ctx.source = next_source
        ctx.archive_listing = None
        logger.debug("container {} re-queued {}", terminal.name, next_source)


def promote_partitions(ctx: WorkContext) -> list[str]:
    """Move/convert partition images into OUTDIR (dumper.sh ~889-933)."""
    work, out = ctx.workdir, ctx.outdir
    out.mkdir(parents=True, exist_ok=True)
    promoted: list[str] = []

    for source_name, out_name in OTHER_PARTITIONS.items():
        if not (work / f"{out_name}.img").exists() and any(
            p.name.startswith(source_name) for p in work.iterdir()
        ):
            src = next(p for p in work.iterdir() if p.name.startswith(source_name))
            src.rename(work / f"{out_name}.img")
        img = work / f"{out_name}.img"
        if not img.is_file():
            continue
        dst = out / f"{out_name}.img"
        to_raw_image(ctx.tools, img, dst)
        if not (dst.exists() and dst.stat().st_size > 0):
            shutil.copy2(img, dst)
        promoted.append(out_name)
        logger.info("{} promoted for {}", out_name, source_name)

    for partition in PARTITIONS:
        img = work / f"{partition}.img"
        if not img.is_file() and ctx.archive_listing is not None and hasattr(
            ctx.archive_listing, "matched_basenames"
        ):
            found = ctx.archive_listing.matched_basenames(f"{partition}.img")
            if found:
                ctx.archive_listing.extract(ctx.tools.seven_zz, work, members=[found[-1]])
        if not img.is_file():
            continue
        dst = out / f"{partition}.img"
        to_raw_image(ctx.tools, img, dst)
        if not (dst.exists() and dst.stat().st_size > 0):
            shutil.copy2(img, dst)
        if partition in EXT4_PARTITIONS and dst.exists() and dst.stat().st_size > 0:
            _strip_if_signed(dst)
        if dst.exists() and dst.stat().st_size == 0:
            dst.unlink(missing_ok=True)
            promoted.append(partition)
        else:
            promoted.append(partition)
        logger.info("partition {} -> {}", partition, dst)

    for chunk in work.glob("super_*.img"):
        shutil.move(str(chunk), str(out / chunk.name))
    return promoted


def _strip_if_signed(dst: Path) -> None:
    tmp = dst.with_name(dst.name + ".x")
    if strip_signed_header(None, dst, tmp):  # type: ignore[arg-type] - tools only used for logging
        shutil.move(str(tmp), str(dst))
    tmp.unlink(missing_ok=True)


def clear_workdir(ctx: WorkContext) -> None:
    work = ctx.workdir
    if work.is_dir():
        for p in work.iterdir():
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink(missing_ok=True)
    logger.debug("work dir cleared: {}", work)


def write_all_files(outdir: Path) -> None:
    """`find OUTDIR -type f -printf '%P\\n' | sort | grep -v .git/`."""
    rels = sorted(
        p.relative_to(outdir).as_posix()
        for p in outdir.rglob("*")
        if p.is_file()
        and not any(part == ".git" for part in p.relative_to(outdir).parts)
    )
    (outdir / "all_files.txt").write_text("\n".join(rels) + "\n", encoding="utf-8")


def fix_permissions(outdir: Path) -> None:
    for p in outdir.rglob("*"):
        if p.is_file() and not p.is_symlink():
            os.chmod(p, p.stat().st_mode | 0o600)
    for p in outdir.rglob("*"):
        if p.is_dir() and not p.is_symlink():
            os.chmod(p, p.stat().st_mode | 0o700)


def remove_sys_journals(outdir: Path) -> None:
    """`find . -mindepth 2 -type d -name "\\[SYS\\]" -exec rm -rf {}`."""
    for p in outdir.rglob("*"):
        if p.is_dir() and p.name == "[SYS]" and p.parent != outdir:
            shutil.rmtree(p, ignore_errors=True)


def finalize(ctx: WorkContext, partitions: list[str]) -> PipelineResult:
    """Post-extraction: partitions, euclid, FS trees, permission/all_files."""
    from dumprx.boot import extract_boot_family
    from dumprx.partitions import identify_super_chunks

    extract_boot_family(ctx.outdir, ctx.tools)
    supers = identify_super_chunks(ctx.outdir, ctx.tools)
    if supers:
        logger.info("super chunks identified: {}", supers)
    extract_euclid_imgs(ctx.outdir, ctx.tools)
    extracted = extract_fs_partitions(ctx.outdir, partitions, ctx.tools)
    remove_sys_journals(ctx.outdir)
    fix_permissions(ctx.outdir)
    write_all_files(ctx.outdir)
    return PipelineResult(outdir=ctx.outdir, terminal="", partitions=partitions, extracted_trees=extracted)


def run_pipeline(ctx: WorkContext) -> PipelineResult:
    """Full extraction from a resolved source: chain -> promote -> finalize."""
    terminal = extract_chain(ctx)
    logger.info("terminal {} consumed input from {}", terminal, ctx.source)
    promoted = promote_partitions(ctx)
    clear_workdir(ctx)
    return finalize(ctx, promoted)


def install_cleanup(workdir: Path) -> None:
    """atexit + SIGINT/SIGTERM: remove the work dir (never OUTDIR).

    Signals abort the run after cleanup; atexit only cleans up on normal exit.
    """

    def handler(*_args) -> None:
        shutil.rmtree(workdir, ignore_errors=True)

    atexit.register(handler)

    def interrupt(*_args) -> None:
        handler()
        raise KeyboardInterrupt

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, interrupt)
        except (ValueError, OSError):  # not the main thread
            pass


__all__ = [
    "PipelineResult",
    "clear_workdir",
    "extract_chain",
    "finalize",
    "fix_permissions",
    "install_cleanup",
    "prepare_listing",
    "promote_partitions",
    "remove_sys_journals",
    "run_pipeline",
    "write_all_files",
]
