"""TWRP device tree generation (twrpdtgen run + wiki README fetch)."""

from __future__ import annotations

import shutil
from pathlib import Path

from loguru import logger

from dumprx.process import run

_TWRPDTGEN = "uvx --from git+https://github.com/twrpdtgen/twrpdtgen@master twrpdtgen"
_WIKI_README = (
    "https://raw.githubusercontent.com/wiki/SebaUbuntu/TWRP-device-tree-generator/"
    "4.-Build-TWRP-from-source.md"
)


def _render_img(outdir: Path, img: str) -> bool:
    result = run([*_TWRPDTGEN.split(), img, "-o", str(outdir)], timeout=600)
    return result.ok


def generate(config, is_ab: bool = False) -> None:
    """Mirror bash 1413-1436: pick recovery/vendor_boot, run twrpdtgen, fetch wiki."""
    outdir = config.paths.outdir

    img = "recovery.img"
    if is_ab:
        if (outdir / "recovery.img").is_file():
            img = "recovery.img"
            logger.info("legacy A/B with recovery partition detected")
        else:
            img = "vendor_boot.img"

    twrp_out = outdir / "twrp-device-tree"
    if not (outdir / img).is_file():
        return

    twrp_out.mkdir(parents=True, exist_ok=True)
    if _render_img(twrp_out, img):
        _fetch_wiki_readme(twrp_out)
    elif (outdir / "vendor_boot.img").is_file():
        if _render_img(twrp_out, "vendor_boot.img"):
            _fetch_wiki_readme(twrp_out)

    _rm_dotgit(twrp_out)


def _fetch_wiki_readme(outdir: Path) -> None:
    target = outdir / "README.md"
    if target.is_file():
        return
    result = run(["curl", "-s", _WIKI_README, "-o", str(target)], timeout=120)
    if not result.ok:
        logger.warning("TWRP wiki README fetch failed (rc={})", result.returncode)


def _rm_dotgit(root: Path) -> None:
    for p in list(root.rglob(".git")):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)


__all__ = ["generate"]
