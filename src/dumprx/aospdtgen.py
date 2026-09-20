"""AOSP/LineageOS device tree generation (vendored aospdtgen DeviceTree fork)."""

from __future__ import annotations

import time

from loguru import logger

from aospdtgen.device_tree import DeviceTree
from dumprx.tools import Tools


def generate(config) -> None:
    """Feed the OUTDIR tree to the vendored DeviceTree, best-effort."""
    outdir = config.paths.outdir
    boot = outdir / "boot.img"
    if not boot.is_file():
        logger.debug("boot.img not found in {}; skipping AOSP device tree", outdir)
        return

    unpack_bootimg = Tools(utilsdir=config.paths.utilsdir)["unpack_bootimg"]
    if unpack_bootimg is None:
        logger.warning("unpack_bootimg not found in utils/bin; skipping AOSP tree")
        return

    logger.info("Generating AOSP device tree from {}...", outdir)
    start = time.monotonic()
    try:
        dump = DeviceTree(
            outdir,
            workdir=config.paths.workdir,
            unpack_bootimg_tool=unpack_bootimg,
        )
        target = (
            outdir
            / "aosp-device-tree"
            / "device"
            / dump.device_info.manufacturer
            / dump.device_info.codename
        )
        logger.debug("Dumping AOSP device tree into {}", target)
        dump.dump_to_folder(target)
        dump.cleanup()
    except Exception as exc:  # noqa: BLE001 - AOSP tree is best-effort
        logger.opt(exception=True).debug("AOSP device tree generation failed with exception:")
        logger.warning("AOSP device tree generation skipped: {}", exc)
        return

    logger.info(
        "AOSP device tree generated at {} in {:.2f}s",
        target,
        time.monotonic() - start,
    )


__all__ = ["generate"]
