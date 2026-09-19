"""Shared super.img handling (bash `superimage_extract`).

Every branch that can emit a super image — the super terminals and the AML
container — funnels through `superimage_extract` so lpunpack ordering, the
`_a`/plain partition fallback, duplicate merges and the archive pull-back stay
in exactly one place.
"""

from __future__ import annotations

from pathlib import Path

from dumprx.config import PARTITIONS
from dumprx.extractors.base import WorkContext
from dumprx.images import super_to_raw, to_raw_image
from dumprx.process import run


def lpunpack_partitions(ctx: WorkContext, raw: Path) -> None:
    """lpunpack every PARTITIONS entry from raw super, tolerant of `_a` names."""
    work = ctx.workdir
    lpunpack = ctx.tools["lpunpack"]
    if lpunpack is None:
        return
    for partition in PARTITIONS:
        if not run(
            [str(lpunpack), f"--partition={partition}_a", str(raw)], cwd=work, capture=True
        ).ok:
            run([str(lpunpack), f"--partition={partition}", str(raw)], cwd=work, capture=True)
        a_img = work / f"{partition}_a.img"
        if a_img.exists():
            a_img.rename(work / f"{partition}.img")


def superimage_extract(ctx: WorkContext, extras: list[Path] | None = None) -> None:
    """Convert workdir super.img to raw and lpunpack all partitions.

    `extras` are duplicate super images (e.g. subfolder copies after `7zz x`)
    merged into the raw image; the archive listing is used as a fallback source
    for partitions the super image did not contain.
    """
    work = ctx.workdir
    super_img = work / "super.img"
    if not super_img.is_file():
        return
    if extras:
        super_to_raw(ctx.tools, super_img, extras[0])
    else:
        to_raw_image(ctx.tools, super_img, work / "super.img.raw")
    raw = work / "super.img.raw"
    if raw.is_file() and raw.stat().st_size > 0:
        lpunpack_partitions(ctx, raw)
    raw.unlink(missing_ok=True)
    listing = ctx.archive_listing
    if listing is not None and hasattr(listing, "matched_basenames"):
        for partition in PARTITIONS:
            if (work / f"{partition}.img").exists():
                continue
            found = listing.matched_basenames(f"{partition}.img")
            if found:
                listing.extract(ctx.tools.seven_zz, work, members=[found[-1]])
    super_img.unlink(missing_ok=True)


def prune_empty_dirs(work: Path) -> None:
    """`find . -type d -empty -delete` equivalent (deepest first)."""
    for d in sorted(
        (p for p in work.rglob("*") if p.is_dir() and not any(p.iterdir())),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        d.rmdir()


__all__ = ["lpunpack_partitions", "prune_empty_dirs", "superimage_extract"]
