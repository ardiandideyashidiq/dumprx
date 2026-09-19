"""Image manipulation: simg2img conversion, signed-header strip, super merge.

Ports the simg2img / MOTO+ASUS header-strip / super.raw merge logic in
dumper.sh. The offset scan runs ONLY after sniffing the first 12 bytes for
the magic, so ordinary Qualcomm images skip the full-image `\\x53\\xEF` scan.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from dumprx.process import run
from dumprx.tools import Tools

_MAGIC_SNIFF = 12
_PATTERN = b"\x53\xEF"
_MOTO_ADJUST = 128055
_MOTO_FINAL = 131072


def simg2img(tools: Tools, srcs: list[Path], dst: Path) -> bool:
    """simg2img one or more (chunked) sparse images into dst. False on failure."""
    binary = tools["simg2img"]
    if binary is None or not srcs:
        return False
    res = run([str(binary), *(str(s) for s in srcs), str(dst)])
    if not res.ok:
        logger.debug("simg2img failed for {} -> {}", srcs[0].name, dst.name)
        return False
    return True


def to_raw_image(tools: Tools, src: Path, dst: Path) -> bool:
    """Convert src to raw dst via simg2img; fall back to a plain copy."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if simg2img(tools, [src], dst):
        return True
    try:
        _copy(src, dst)
        return True
    except OSError as exc:
        logger.warning("copy fallback failed {}: {}", src, exc)
        return False


def strip_signed_header(tools: Tools, img: Path, out: Path) -> bool:
    """Strip a MOTO/ASUS signed header off img into out. Sniffs magic first.

    Returns True when a header was actually stripped (out re-written).
    """
    try:
        with img.open("rb") as fh:
            magic = fh.read(_MAGIC_SNIFF)
    except OSError as exc:
        logger.warning("cannot read {}: {}", img, exc)
        return False

    is_moto = b"MOTO" in magic
    is_asus = b"ASUS" in magic
    if not (is_moto or is_asus):
        return False

    pos = _find_pattern(img)
    if pos is None:
        logger.debug("no \\x53\\xEF pattern in {} despite {} magic", img.name, magic[:4])
        return False
    offset = pos - 1080
    if is_moto and offset == _MOTO_ADJUST:
        logger.debug("MOTO header offset adjust {} -> {}", offset, _MOTO_FINAL)
        offset = _MOTO_FINAL
    logger.info("{} header on {} at {}", "MOTO" if is_moto else "ASUS", img.name, offset)
    if offset <= 0:
        return False
    try:
        with img.open("rb") as fh:
            fh.seek(offset)
            data = fh.read()
        out.write_bytes(data)
        return True
    except OSError as exc:
        logger.warning("header strip failed {}: {}", img, exc)
        return False


def _find_pattern(img: Path) -> int | None:
    """First `\\x53\\xEF` byte offset, streamed without loading the whole image."""
    chunk_size = 1 << 20
    offset = 0
    overlap = b""
    try:
        with img.open("rb") as fh:
            while True:
                chunk = fh.read(chunk_size)
                if not chunk:
                    return None
                window = overlap + chunk
                idx = window.find(_PATTERN)
                if idx != -1:
                    return offset - len(overlap) + idx
                offset += len(chunk)
                overlap = chunk[-2:]
    except OSError:
        return None


def super_to_raw(tools: Tools, super_file: Path, extra: Path | None = None) -> bool:
    """Produce super.img.raw next to super.img; merges when extra given."""
    raw = super_file.with_name(super_file.name + ".raw")
    if extra is None:
        return to_raw_image(tools, super_file, raw)
    if simg2img(tools, [super_file, extra], raw):
        super_file.unlink(missing_ok=True)
        extra.unlink(missing_ok=True)
        return True
    logger.warning("super merge failed; using single super.img")
    return to_raw_image(tools, super_file, raw)


def merge_sparse_chunks(tools: Tools, chunks: list[Path], dst: Path) -> bool:
    """simg2img sparsechunk files into a single raw dst."""
    if not chunks:
        return False
    return simg2img(tools, chunks, dst)


def _copy(src: Path, dst: Path) -> None:
    import shutil

    with src.open("rb") as fh_src, dst.open("wb") as fh_dst:
        shutil.copyfileobj(fh_src, fh_dst, length=1 << 20)


__all__ = [
    "merge_sparse_chunks",
    "simg2img",
    "strip_signed_header",
    "super_to_raw",
    "to_raw_image",
]
