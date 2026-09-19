#
# Copyright (C) 2022 The Android Open Source Project
#
# SPDX-License-Identifier: Apache-2.0
#
"""AOSP mkbootimg/unpack_bootimg backed boot image reader.

Replaces the old AIK (Android Image Kitchen) unpacking with the vendored
AOSP ``unpack_bootimg.py`` script so that modern images (vendor_boot v3/v4,
init_boot) are supported. Runs ``unpack_bootimg --format=mkbootimg`` and maps
its shell-escaped argument line plus the extracted blob files onto the
``ImageInfo`` surface consumed by the templates.
"""

from __future__ import annotations

import gzip
import lzma
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

AVB_FOOTER_MAGIC = b"AVBf"

# AIK-derived address convention kept for parity with the legacy dumper:
# the kernel offset is assumed to be 0x8000, so base = kernel_load - 0x8000
# and every other offset is the load address minus the base.
KERNEL_OFFSET = 0x8000

# Priority order for adaptive selection: recovery is best for TWRP, then
# vendor_boot (GKI), then init_boot, then a plain boot.img as last resort.
IMAGE_PRIORITY = ("recovery", "vendor_boot", "init_boot", "boot")

VENDOR_RAMDISK_TYPE_RECOVERY = 2


@dataclass
class ImageInfo:
    header_version: str = "0"
    base_address: str | None = None
    cmdline: str | None = None
    pagesize: str | None = None
    ramdisk_offset: str | None = None
    tags_offset: str | None = None
    origsize: int = 0
    ramdisk_compression: str = ""
    sigtype: str = ""
    kernel: Path | None = None
    dt: Path | None = None
    dtb: Path | None = None
    dtbo: Path | None = None
    ramdisk: Path | None = None


def select_primary(images: list[Path]) -> Path:
    """Pick the best image to build the recovery tree from.

    Unknown filenames (e.g. ``rescue.img``) rank lowest, so any real
    partition image wins over them.
    """
    def rank(image: Path) -> int:
        return IMAGE_PRIORITY.index(image.name) if image.name in IMAGE_PRIORITY else len(
            IMAGE_PRIORITY
        )

    return sorted(images, key=rank)[0]


def _run(tool: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(tool), *args], check=True, capture_output=True, text=True
    )


def _parse_unpack_output(text: str) -> dict[str, str]:
    text = text.rstrip("\x00").strip()
    if "\x00" in text:
        args = text.split("\x00")
    else:
        args = shlex.split(text)
    return {args[i]: args[i + 1] for i in range(0, len(args) - 1, 2)}


def _hex(value: str) -> int:
    return int(value, 16)


def _has_avb_footer(image: Path) -> bool:
    """Best-effort AVBv2 detection: look for the footer magic at the image tail."""
    with open(image, "rb") as handle:
        handle.seek(0, 2)
        tail = handle.read(min(handle.tell(), 4096))
    return AVB_FOOTER_MAGIC in tail


def extract_ramdisk(blob_path: Path, dest_dir: Path) -> str:
    """Decompress and cpio-extract a ramdisk blob; returns its compression id.

    Raises ``AssertionError`` when the ramdisk is missing or empty so the
    caller upstream (DeviceTree) can surface the "Ramdisk not found" failure.
    """
    if not blob_path.is_file():
        raise AssertionError("Ramdisk not found")

    data = blob_path.read_bytes()
    if len(data) == 0:
        raise AssertionError("Ramdisk not found")

    if data.startswith(b"\x1f\x8b"):
        raw_cpio = gzip.decompress(data)
        compression = "gzip"
    elif data.startswith((b"\xfd7zXZ", b"\x5d\x00\x00")):
        raw_cpio = lzma.decompress(data)
        compression = "lzma"
    elif data.startswith(b"\x04\x22\x4d\x18"):
        raw_cpio = subprocess.run(
            ["lz4", "-d"], input=data, check=True, capture_output=True
        ).stdout
        compression = "lz4"
    elif data.startswith(b"\x28\xb5\x2f\xfd"):
        raw_cpio = subprocess.run(
            ["zstd", "-d"], input=data, check=True, capture_output=True
        ).stdout
        compression = "zstd"
    elif data.startswith(b"070701"):
        raw_cpio = data
    else:
        raise AssertionError(f"Unknown ramdisk compression: {data[:4]!r}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["cpio", "-idm"], input=raw_cpio, check=True, cwd=dest_dir, capture_output=True
    )
    return compression


def _unpack_one(image: Path, outdir: Path, tool: Path) -> tuple[ImageInfo, dict[str, str]]:
    pairs = _parse_unpack_output(
        _run(
            tool,
            "--boot_img",
            str(image),
            "--out",
            str(outdir),
            "--format",
            "mkbootimg",
            "--null",
        ).stdout
    )

    info = ImageInfo(
        header_version=pairs.get("--header_version", "0"),
        origsize=image.stat().st_size,
        sigtype="AVBv2" if _has_avb_footer(image) else "",
    )

    kernel_load = _hex(pairs["--kernel_offset"])
    base = kernel_load - KERNEL_OFFSET
    info.base_address = f"0x{base:08x}"
    if pairs.get("--pagesize"):
        info.pagesize = str(_hex(pairs["--pagesize"]))
    cmdline = pairs.get("--cmdline") or pairs.get("--vendor_cmdline")
    if cmdline:
        info.cmdline = cmdline
    if pairs.get("--ramdisk_offset"):
        info.ramdisk_offset = f"0x{_hex(pairs['--ramdisk_offset']) - base:08x}"
    if pairs.get("--tags_offset"):
        info.tags_offset = f"0x{_hex(pairs['--tags_offset']) - base:08x}"

    for name, attr in (("kernel", "kernel"), ("dtb", "dtb"), ("recovery_dtbo", "dtbo")):
        blob = outdir / name
        if blob.is_file():
            setattr(info, attr, blob)

    ramdisk_dir = outdir / "ramdisk-extracted"
    ramdisk_blob = outdir / "ramdisk"
    fragment = _pick_vendor_ramdisk_fragment(pairs)
    if ramdisk_blob.is_file():
        blob = ramdisk_blob
    elif fragment is not None:
        blob = fragment
    else:
        blob = None
    if blob is not None:
        info.ramdisk_compression = extract_ramdisk(blob, ramdisk_dir)
        info.ramdisk = ramdisk_dir

    return info, pairs


def _pick_vendor_ramdisk_fragment(pairs: dict[str, str]) -> Path | None:
    """For vendor_boot v4 return the recovery ramdisk fragment, else the first."""
    fragments: list[tuple[Path, int]] = []
    last_type: str | None = None
    for key, value in pairs.items():
        if key == "--ramdisk_type":
            last_type = value
        elif key == "--vendor_ramdisk_fragment":
            fragments.append((Path(value), int((last_type or "1") or "1")))
            last_type = None
    if not fragments:
        return None
    recovery = [path for path, rtype in fragments if rtype == VENDOR_RAMDISK_TYPE_RECOVERY]
    return (recovery or [fragments[0][0]])[0]


def unpack_images(
    images: list[Path], workdir: Path, unpack_bootimg_tool: Path | None = None
) -> ImageInfo:
    """Unpack the best image and merge metadata from the auxiliary ones."""
    if unpack_bootimg_tool is None:
        found = shutil.which("unpack_bootimg")
        if not found:
            raise FileNotFoundError("unpack_bootimg not found, pass unpack_bootimg_tool")
        unpack_bootimg_tool = Path(found)

    primary = select_primary(images)
    run_dir = workdir / "bootimg-unpack"
    run_dir.mkdir(parents=True, exist_ok=True)

    info, _ = _unpack_one(primary, run_dir / primary.stem, unpack_bootimg_tool)

    for image in images:
        if image == primary:
            continue
        aux, _ = _unpack_one(image, run_dir / image.stem, unpack_bootimg_tool)
        if info.dtb is None and aux.dtb is not None:
            info.dtb = aux.dtb
        if info.dt is None and aux.dt is not None:
            info.dt = aux.dt
        if not info.cmdline and aux.cmdline:
            info.cmdline = aux.cmdline

    return info