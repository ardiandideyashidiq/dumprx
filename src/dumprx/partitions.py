"""Filesystem partition extraction and super-chunk identification.

Ports dumper.sh's parallel fsck.erofs -> 7zz -> mount-loop chain plus the
super_*.img chunk identification pass. Mount-loop needs `sudo`; failures are
logged and never abort the dump (matches bash tolerance).
"""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from loguru import logger

from dumprx.process import run
from dumprx.tools import Tools

BOOT_KEEP = ("boot", "recovery", "dtbo", "tz", "vbmeta")


def extract_fs_partition(root: Path, name: str, tools: Tools) -> bool:
    img = root / f"{name}.img"
    part_dir = root / name

    # modem is raw (not a filesystem) — leave the .img as-is on erofs failure
    if name == "modem" or not img.is_file():
        return False
    part_dir.mkdir(exist_ok=True)

    fsck = tools["fsck.erofs"]
    if fsck is not None and run([str(fsck), f"--extract={part_dir}", str(img)]).ok:
        img.unlink(missing_ok=True)
        return True

    for p in part_dir.iterdir():
        if p.is_dir():
            continue
        p.unlink(missing_ok=True)
    zz = tools.seven_zz
    if run([zz, "x", "-snld", str(img), "-y", f"-o{part_dir}/"]).ok:
        img.unlink(missing_ok=True)
        return True

    logger.warning("7zz extraction failed for {}; trying mount loop", name)
    return _mount_loop_extract(img, part_dir)


def _mount_loop_extract(img: Path, part_dir: Path) -> bool:
    work = part_dir.parent / f"{part_dir.name}_"
    work.mkdir(exist_ok=True)
    try:
        if not run(["sudo", "mount", "-o", "loop", "-t", "auto", str(img), str(part_dir)]).ok:
            return False
        copied = run(
            ["sudo", "cp", "-a", f"{part_dir}/.", f"{work}/"]
        ).ok
        run(["sudo", "umount", str(part_dir)])
        if not copied:
            return False
        run(["sudo", "cp", "-a", f"{work}/.", f"{part_dir}/"])
        run(["sudo", "chown", "-R", str(os.getuid()), f"{part_dir}/"])
        run(["chmod", "-R", "u+rwX", f"{part_dir}/"])
        img.unlink(missing_ok=True)
        return True
    except Exception as exc:  # noqa: BLE001 - sudo may be unavailable
        logger.warning("mount loop extraction failed for {}: {}", part_dir.name, exc)
        return False
    finally:
        run(["sudo", "rm", "-rf", str(work)])


def extract_fs_partitions(
    root: Path, partitions: list[str], tools: Tools, jobs: int | None = None
) -> dict[str, bool]:
    """Extract all FS partitions in parallel, capped by `jobs` (nproc by default).

    Skips boot-family/tz/vbmeta exactly like dumper.sh.
    """
    if jobs is None:
        jobs = min(4, int(os.cpu_count() or 4))
    skip = {"boot", "init_boot", "recovery", "dtbo", "vendor_boot", "tz", "vbmeta"}
    targets = [p for p in partitions if p not in skip and (root / f"{p}.img").exists()]
    if not targets:
        return {}

    results: dict[str, bool] = {}

    def work(p: str) -> tuple[str, bool]:
        try:
            return p, extract_fs_partition(root, p, tools)
        except Exception as exc:  # noqa: BLE001 - one partition must not kill all
            logger.warning("partition {} failed: {}", p, exc)
            return p, False

    with ThreadPoolExecutor(max_workers=jobs, thread_name_prefix="fs-extract") as pool:
        for name, ok in pool.map(work, targets):
            results[name] = ok
    return results


def identify_super_chunks(outdir: Path, tools: Tools) -> list[str]:
    """Identify and move super_2..17.img chunks to their partition dirs."""
    fsck = tools["fsck.erofs"]
    if fsck is None:
        return []
    identified: list[str] = []
    for i in range(2, 18):
        chunk = outdir / f"super_{i}.img"
        if not chunk.is_file() or not run([str(fsck), str(chunk)]).ok:
            continue
        temp = outdir / f"temp_chunk_{i}"
        if temp.exists():
            _rmtree(temp)
        temp.mkdir()
        if not run([str(fsck), f"--extract={temp}", str(chunk)]).ok:
            _rmtree(temp)
            continue
        name = _identity_of(temp)
        final = _dedupe_path(outdir, name)
        os.replace(temp, final)
        identified.append(f"super_{i}: {name}")
        logger.info("Chunk super_{} identified as [{}] -> {}", i, name, final.name)
    return identified


def _identity_of(temp: Path) -> str:
    if any(p.match("*lib/modules/*android*") for p in temp.rglob("lib/modules/*")):
        return "system_dlkm"
    entries = list(temp.iterdir())
    if len(entries) == 1 and entries[0].is_file() and entries[0].name == "build.prop":
        return "tr_manifest"
    for candidate in ("build.prop", "etc/build.prop", "system/build.prop"):
        prop_file = temp / candidate
        if prop_file.is_file():
            text = prop_file.read_text(encoding="utf-8", errors="replace")
            match = re.search(r"ro\.product\.([^.]+)", text)
            if match:
                return match.group(1)
    return "unknown"


def _dedupe_path(base: Path, name: str) -> Path:
    final = base / name
    counter = 2
    while final.exists():
        final = base / f"{name}_{counter}"
        counter += 1
    return final


def extract_euclid_imgs(outdir: Path, tools: Tools) -> None:
    """7zz-extract *.img blobs inside Oppo euclid dirs (props source)."""
    zz = tools.seven_zz
    for sub in ("vendor/euclid", "system/system/euclid"):
        euclid = outdir / sub
        if not euclid.is_dir():
            continue
        for img in sorted(euclid.glob("*.img")):
            target = euclid / img.stem
            run([zz, "x", str(img), f"-o{target}"])
            img.unlink(missing_ok=True)


def _rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


__all__ = [
    "extract_euclid_imgs",
    "extract_fs_partition",
    "extract_fs_partitions",
    "identify_super_chunks",
]
