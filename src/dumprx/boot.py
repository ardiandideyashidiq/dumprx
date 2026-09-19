"""Boot-family extraction: dts/dtb, unpackboot, avb info, ikconfig, vmlinux.

Ports dumper.sh's boot.img / vendor_boot.img / init_boot.img / recovery.img /
dtbo.img processing. All steps are best-effort; failures only log.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from dumprx.process import run
from dumprx.tools import Tools


def extract_boot_family(outdir: Path, tools: Tools) -> None:
    _extract_boot(outdir, tools)
    _extract_boot(outdir, tools, name="vendor_boot")
    _unpack_only(outdir, tools, "init_boot")
    _unpack_only(outdir, tools, "recovery")
    dtbo = outdir / "dtbo.img"
    if dtbo.exists():
        _extract_dtb_dts(dtbo, outdir / "dtbo", outdir / "dtbodts", tools)
        logger.info("dtbo extracted")


def _extract_boot(outdir: Path, tools: Tools, name: str = "boot") -> None:
    img = outdir / f"{name}.img"
    if not img.exists():
        return
    img_dir = outdir / f"{name}img"
    dts_dir = outdir / f"{name}dts"
    unpack_to = outdir / name
    _extract_dtb_dts(img, img_dir, dts_dir, tools)
    run(["bash", str(tools["unpackboot"]), str(img), str(unpack_to)])
    logger.info("{} extracted", name if name != "boot" else "Boot")

    if name == "boot":
        _extract_avb(img, unpack_to / "avb.txt", tools)
        re_dir = outdir / "bootRE"
        re_dir.mkdir(exist_ok=True)
        ik = re_dir / "ikconfig"
        res = run(["bash", str(tools["extract-ikconfig"]), str(img)], capture=True)
        if res.ok and res.stdout:
            ik.write_bytes(res.stdout)
        korig = outdir / "vendor_boot.img"
        ksrc = img if not korig.exists() else unpack_to / "kernel"
        _kallsyms(ksrc, re_dir / ("kernel_kallsyms.txt" if korig.exists() else "boot_kallsyms.txt"), tools)
        run(["python3", str(tools["vmlinux-to-elf"]), str(img), str(re_dir / "boot.elf")])
        logger.info("boot.elf generated")
        _dtb_img_unpack(outdir / "boot" / "dtb.img", outdir / "dtbimg", tools)
    elif name == "vendor_boot":
        re_dir = outdir / "vendor_bootRE"
        re_dir.mkdir(exist_ok=True)
        run(["python3", str(tools["vmlinux-to-elf"]), str(img), str(re_dir / "vendor_boot.elf")])
        logger.info("vendor_boot.elf generated")
        _dtb_img_unpack(outdir / "vendor_boot" / "dtb.img", outdir / "vendor_dtbimg", tools)


def _unpack_only(outdir: Path, tools: Tools, name: str) -> None:
    img = outdir / f"{name}.img"
    if img.exists():
        run(["bash", str(tools["unpackboot"]), str(img), str(outdir / name)])
        logger.info("{} extracted", name.replace("_", " ").title())


def _extract_avb(img: Path, out_txt: Path, tools: Tools) -> None:
    res = run(
        ["python3", str(tools["avbtool"]), "info_image", "--image", str(img)],
        capture=True,
    )
    if res.ok:
        out_txt.write_bytes(res.stdout)
    else:
        logger.debug("avbtool info_image failed for {}", img.name)


def _kallsyms(src: Path, target: Path, tools: Tools) -> None:
    finder = tools["kallsyms-finder"]
    if finder is None or not src.exists():
        return
    res = run(["python3", str(finder), str(src)], capture=True)
    # bash threw stdout to /dev/null; capturing real output is strictly better
    target.write_bytes(res.stdout or b"")
    logger.info("{} generated", target.name)


def _extract_dtb_dts(img: Path, out_dir: Path, dts_dir: Path, tools: Tools) -> None:
    out_dir.mkdir(exist_ok=True)
    dts_dir.mkdir(exist_ok=True)
    if not run(["uvx", "-q", "extract-dtb", str(img), "-o", str(out_dir)]).ok:
        logger.debug("extract-dtb failed for {}", img.name)
        return
    dtc = tools["dtc"]
    if dtc is None:
        return
    for dtb in sorted(out_dir.glob("*.dtb")):
        out_dts = (dts_dir / dtb.name).with_suffix(".dts")
        run([str(dtc), "-q", "-s", "-f", "-I", "dtb", "-O", "dts", "-o", str(out_dts), str(dtb)])


def _dtb_img_unpack(dtb_img: Path, target: Path, tools: Tools) -> None:
    if dtb_img.exists():
        target.mkdir(exist_ok=True)
        run(["uvx", "-q", "extract-dtb", str(dtb_img), "-o", str(target)])


__all__ = ["extract_boot_family"]
