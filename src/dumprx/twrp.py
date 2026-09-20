"""TWRP device tree generation (vendored twrpdtgen DeviceTree + wiki README fetch)."""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from loguru import logger

from dumprx.tools import Tools
from twrpdtgen import module_path
from twrpdtgen.device_tree import DeviceTree

_VENDORED_WIKI_README = module_path / "templates" / "wiki_README.md"

# Candidates in twrpdtgen priority order (best ambiguity for TWRP first).
IMAGE_CANDIDATES = ("recovery.img", "vendor_boot.img", "init_boot.img", "boot.img")


def generate(config, info: Any | None = None) -> None:
    """Feed the OUTDIR boot-image set to the vendored DeviceTree, best-effort."""
    outdir = config.paths.outdir
    images = [outdir / name for name in IMAGE_CANDIDATES if (outdir / name).is_file()]
    if not images:
        logger.debug("No boot image candidates found in {}; skipping TWRP tree", outdir)
        return

    logger.debug("TWRP candidate images found: {}", [img.name for img in images])
    unpack_bootimg = Tools(utilsdir=config.paths.utilsdir)["unpack_bootimg"]
    if unpack_bootimg is None:
        logger.warning("unpack_bootimg not found in utils/bin; skipping TWRP tree")
        return

    twrp_out = outdir / "twrp-device-tree" / "device"
    dtbo = outdir / "dtbo.img" if (outdir / "dtbo.img").is_file() else None
    logger.info("Generating TWRP device tree into {}...", twrp_out)
    start = time.monotonic()
    try:
        tree = DeviceTree(
            images=images,
            unpack_bootimg_tool=unpack_bootimg,
            workdir=config.paths.workdir,
            dtbo=dtbo,
            firmware_info=info,
        )
        target = tree.dump_to_folder(twrp_out)
        logger.info(
            "TWRP device tree generated at {} in {:.2f}s",
            target,
            time.monotonic() - start,
        )
    except Exception as exc:  # noqa: BLE001 - TWRP tree is best-effort
        logger.opt(exception=True).debug("TWRP device tree generation failed with exception:")
        logger.warning("TWRP device tree generation skipped: {}", exc)
        return

    _install_wiki_readme(twrp_out)
    _rm_dotgit(twrp_out)


def _install_wiki_readme(outdir: Path) -> None:
    target = outdir / "README.md"
    if target.is_file():
        return
    if _VENDORED_WIKI_README.is_file():
        shutil.copyfile(_VENDORED_WIKI_README, target)


# Backwards-compatibility alias for tests
_fetch_wiki_readme = _install_wiki_readme


def _rm_dotgit(root: Path) -> None:
    for p in list(root.rglob(".git")):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)


__all__ = ["generate"]
