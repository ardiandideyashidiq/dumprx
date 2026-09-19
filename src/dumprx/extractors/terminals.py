"""Terminal extractors: the dumper.sh raw-partition chain (order 10+).

Each terminal runs after all containers and produces partition images. Every
detect matches the bash `ARCHIVE_LISTING` grep OR its work-dir `find` twin,
first-match-wins, exactly like the `elif` chain. Extraction is best-effort:
failures log and continue (the pipeline only aborts on unsupported input).
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from loguru import logger

from dumprx.config import PARTITIONS
from dumprx.extractors.base import Extractor, WorkContext, extractor
from dumprx.extractors.super import prune_empty_dirs, superimage_extract
from dumprx.images import merge_sparse_chunks
from dumprx.process import run


def _names(ctx: WorkContext) -> list[str]:
    listing = ctx.archive_listing
    return list(listing.member_names) if listing is not None else []


def _work_find(ctx: WorkContext, glob: str) -> list[Path]:
    return sorted(ctx.workdir.glob(glob))


def _detect_file_or_work(ctx: WorkContext, pat: str, glob: str) -> bool:
    listing = ctx.archive_listing
    if listing is not None and listing.has(pat):
        return True
    return bool(_work_find(ctx, glob))


def _any_name(ctx: WorkContext, pat: str) -> bool:
    return any(re.search(pat, n) for n in _names(ctx))


def _has_large_nested(ctx: WorkContext) -> bool:
    for base in ("*.rar", "*.zip", "*.7z", "*.tar"):
        for p in _work_find(ctx, base):
            if p.is_file() and p.stat().st_size > 300 * 1024 * 1024:
                return True
    return False


@extractor(10, "terminal")
class DatTerminal(Extractor):
    name = "dat"

    def detect(self, ctx: WorkContext) -> bool:
        return _detect_file_or_work(ctx, r"system\.new\.dat", "system.new.dat*")

    def extract(self, ctx: WorkContext) -> None:
        work = ctx.workdir
        listing = ctx.archive_listing
        for partition in PARTITIONS:
            if listing is not None:
                listing.extract(
                    ctx.tools.seven_zz, work,
                    members=[f"{partition}.new.dat*", f"{partition}.transfer.list", f"{partition}.img"],
                )
                listing.extract(
                    ctx.tools.seven_zz, work,
                    members=[f"{partition}.*.new.dat*", f"{partition}.*.transfer.list", f"{partition}.*.img"],
                )
            _rename_oplus_digits(work)
            _concat_dat_parts(work / f"{partition}.new.dat")
            for new_dat in sorted(work.glob("*.new.dat*")):
                _decode_and_sdat(ctx, new_dat)


def _rename_oplus_digits(work: Path) -> None:
    """`rename 's/(\\w+)\\.(\\d+)\\.(\\w+)/$1.$3/' *` (Oplus NV-ID digits)."""
    pat = re.compile(r"^(\w+)\.(\d+)\.(\w+)$")
    for p in list(work.iterdir()):
        m = pat.match(p.name)
        if m and m.group(2).isdigit():
            p.rename(work / f"{m.group(1)}.{m.group(3)}")


def _concat_dat_parts(base: Path) -> None:
    """Streaming `cat {base}.{0..999} >> base` — numeric order, one chunk at a time."""
    marker = Path(str(base) + ".1")
    if not marker.is_file():
        return
    parts = []
    for p in base.parent.glob(f"{base.name}.*"):
        digits = p.name.rsplit(".", 1)[-1]
        if digits.isdigit():
            parts.append((int(digits), p))
    with base.open("ab") as out:
        for _, part in sorted(parts):
            with part.open("rb") as src:
                shutil.copyfileobj(src, out, length=1 << 20)
            part.unlink(missing_ok=True)


def _decode_and_sdat(ctx: WorkContext, new_dat: Path) -> None:
    work = ctx.workdir
    name = new_dat.name
    line = name.split(".")[0]
    if ".dat.xz" in name:
        run([ctx.tools.seven_zz, "e", "-y", str(new_dat)], cwd=work, capture=True)
        new_dat.unlink(missing_ok=True)
    if ".dat.br" in name:
        logger.info("Converting brotli {} to normal", new_dat.name)
        if run(["brotli", "-d", str(new_dat)], cwd=work, capture=True).ok:
            unc = work / (name[: -len(".dat.br")] + ".dat")
            if unc.is_file():
                new_dat.unlink(missing_ok=True)
    resolved = work / f"{line}.new.dat" if (work / f"{line}.new.dat").exists() else new_dat
    transfer = work / f"{line}.transfer.list"
    sdat2img = ctx.tools["sdat2img"]
    if not (transfer.is_file() and resolved.is_file() and sdat2img is not None):
        return
    out_img = ctx.outdir / f"{line}.img"
    run(["python3", str(sdat2img), str(transfer), str(resolved), str(out_img)], cwd=work, capture=True)
    transfer.unlink(missing_ok=True)
    resolved.unlink(missing_ok=True)


@extractor(11, "terminal")
class QfilTerminal(Extractor):
    name = "qfil"

    def detect(self, ctx: WorkContext) -> bool:
        return _detect_file_or_work(ctx, r"rawprogram", "rawprogram*")

    def extract(self, ctx: WorkContext) -> None:
        work = ctx.workdir
        listing = ctx.archive_listing
        if listing is not None:
            rawprograms = listing.matched_names("rawprogram")
            listing.extract(ctx.tools.seven_zz, work, members=rawprograms or ["dummypartition"])
        for partition in PARTITIONS:
            partitionsonzip = [n for n in _names(ctx) if partition in n]
            if not partitionsonzip:
                continue
            if listing is not None:
                listing.extract(ctx.tools.seven_zz, work, members=partitionsonzip)
            p_img = work / f"{partition}.img"
            if p_img.is_file():
                continue
            raw_img = work / f"{partition}.raw.img"
            if raw_img.is_file():
                raw_img.rename(p_img)
                continue
            xml = work / "rawprogram_unsparse0.xml"
            if not xml.is_file():
                continue
            run([str(ctx.tools["packsparseimg"]), "-t", partition, "-x", str(xml)], cwd=work, capture=True)
            raw = work / f"{partition}.raw"
            if raw.exists():
                raw.rename(p_img)
        if (work / "super.img").is_file():
            superimage_extract(ctx)


@extractor(12, "terminal")
class Nb0Terminal(Extractor):
    name = "nb0"

    def detect(self, ctx: WorkContext) -> bool:
        return _detect_file_or_work(ctx, r".*\.nb0", "*.nb0*")

    def extract(self, ctx: WorkContext) -> None:
        work = ctx.workdir
        listing = ctx.archive_listing
        if listing is not None:
            to_extract = listing.matched_names(r".*\.nb0")
            listing.extract(ctx.tools.seven_zz, work, members=to_extract or ["dummypartition"], flat=False)
            target = to_extract[0] if to_extract else None
        else:
            target = next((p.name for p in work.glob("*.nb0")), None)
        nb0 = ctx.tools["nb0-extract"]
        if nb0 is None or target is None:
            return
        run([str(nb0), target, str(work)], cwd=work)


@extractor(13, "terminal")
class ChunkTerminal(Extractor):
    name = "chunk"

    def detect(self, ctx: WorkContext) -> bool:
        listing = ctx.archive_listing
        if listing is not None:
            chunk_lines = [ln for ln in listing.entries() if "system" in ln and "chunk" in ln]
            if any(not re.search(r"\.so$", ln) for ln in chunk_lines):
                return True
        return bool(_work_find(ctx, "system*chunk*"))

    def extract(self, ctx: WorkContext) -> None:
        work = ctx.workdir
        listing = ctx.archive_listing
        for partition in PARTITIONS:
            if listing is not None:
                found = [n for n in _names(ctx) if re.search(rf"{partition}\.img", n)]
                listing.extract(
                    ctx.tools.seven_zz, work,
                    members=[f"*{partition}*chunk*", *found],
                )
            else:
                for p in list(work.glob(f"*{partition}*chunk*")) + list(work.glob(f"*{partition}*.img")):
                    shutil.move(str(p), str(work / p.name))
            if not (work / f"{partition}.img").exists():
                for pat in (f"*{partition}_b*", f"*{partition}_other*"):
                    for p in list(work.glob(pat)):
                        p.unlink(missing_ok=True)
            chunks = _work_find(ctx, f"*{partition}*chunk*")
            if chunks and not (work / f"{partition}.img").exists():
                if merge_sparse_chunks(ctx.tools, chunks, work / f"{partition}.img.raw"):
                    (work / f"{partition}.img.raw").rename(work / f"{partition}.img")
                for c in chunks:
                    c.unlink(missing_ok=True)


@extractor(14, "terminal")
class RawImageTerminal(Extractor):
    name = "rawimage"

    def detect(self, ctx: WorkContext) -> bool:
        if _any_name(ctx, r"system_new\.img|^system\.img|/system\.img|system_image\.emmc\.img"):
            return True
        return bool(_work_find(ctx, "system*.img"))

    def extract(self, ctx: WorkContext) -> None:
        work = ctx.workdir
        if ctx.archive_listing is not None:
            ctx.archive_listing.extract_all(ctx.tools.seven_zz, work, flat=False)
        for suffix, target in (("_image.emmc.img", ".img"), ("_new.img", ".img"), (".img.ext4", ".img")):
            for p in list(work.rglob(f"*{suffix}")):
                if p.is_file():
                    p.rename(work / (p.name[: -len(suffix)] + target))
        for p in list(work.glob("*/*.img")):
            shutil.move(str(p), str(work / p.name))
        for f in list(work.rglob("*Android_scatter.txt")) + list(work.rglob("*Android_scatter.xml")):
            shutil.move(str(f), str(ctx.outdir / f.name))
        for f in list(work.rglob("DA_BR.bin")):
            (ctx.outdir / "download_agent").mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(ctx.outdir / "download_agent" / f.name))
        for f in list(work.rglob("*Release_Note.txt")):
            shutil.move(str(f), str(ctx.outdir / f.name))
        for p in list(work.iterdir()):
            if p.is_file() and "img" not in p.name.lower():
                p.unlink(missing_ok=True)


@extractor(15, "terminal")
class SinTerminal(Extractor):
    name = "sin"

    def detect(self, ctx: WorkContext) -> bool:
        if ctx.archive_listing is not None and ctx.archive_listing.has(r"system\.sin|system_.*\.sin"):
            return True
        return bool(_work_find(ctx, "system*.sin"))

    def extract(self, ctx: WorkContext) -> None:
        work = ctx.workdir
        listing = ctx.archive_listing
        if listing is not None:
            listing.extract_all(ctx.tools.seven_zz, work, flat=False)
        to_remove = ""
        for marker in ("boot_", "cache_", "vendor_"):
            to_remove = _sin_common_tail(work, marker)
            if to_remove:
                break
        for p in list(work.glob("*/*.sin")):
            shutil.move(str(p), str(work / p.name))
        if to_remove:
            for p in list(work.glob(f"*_{to_remove}.sin")):
                p.rename(work / (p.name[: -len(f"_{to_remove}.sin")] + ".sin"))
        if ctx.tools["unsin"] is not None:
            run([str(ctx.tools["unsin"]), "-d", str(work)], capture=True)
        for p in list(work.glob("*.ext4")):
            p.rename(work / (p.name[: -len(".ext4")] + ".img"))
        supers = _work_find(ctx, "super_*.img")
        if supers:
            shutil.move(str(supers[0]), str(work / "super.img"))
            logger.info("super image inside a sin detected")
            superimage_extract(ctx)


def _sin_common_tail(work: Path, marker: str) -> str:
    for p in work.rglob(f"*{marker}*.sin"):
        m = re.search(rf"{marker}(.*)\.sin", p.name)
        if m:
            return m.group(1)
    return ""


@extractor(16, "terminal")
class PacTerminal(Extractor):
    name = "pac"

    def detect(self, ctx: WorkContext) -> bool:
        return _detect_file_or_work(ctx, r"\.pac$", "*.pac")

    def extract(self, ctx: WorkContext) -> None:
        work = ctx.workdir
        if ctx.archive_listing is not None:
            ctx.archive_listing.extract_all(ctx.tools.seven_zz, work, flat=False)
        pacextractor = ctx.tools["pacExtractor"]
        if pacextractor is None:
            return
        for pac in sorted(work.rglob("*.pac")):
            run(["python3", str(pacextractor), str(pac), str(work)], cwd=work)
        if (work / "super.img").is_file():
            superimage_extract(ctx)


@extractor(17, "terminal")
class BinTerminal(Extractor):
    name = "bin"

    def detect(self, ctx: WorkContext) -> bool:
        return _detect_file_or_work(ctx, r"system\.bin", "system.bin*")

    def extract(self, ctx: WorkContext) -> None:
        work = ctx.workdir
        if ctx.archive_listing is not None:
            ctx.archive_listing.extract_all(ctx.tools.seven_zz, work, flat=False)
        for p in list(work.glob("*/*.bin")):
            shutil.move(str(p), str(work / p.name))
        for p in list(work.glob("*.bin")):
            p.rename(work / (p.name[:-4] + ".img"))


@extractor(18, "terminal")
class PsuffixTerminal(Extractor):
    name = "psuffix"

    def detect(self, ctx: WorkContext) -> bool:
        return _detect_file_or_work(ctx, r"system-p", "system-p*")

    def extract(self, ctx: WorkContext) -> None:
        work = ctx.workdir
        listing = ctx.archive_listing
        for partition in PARTITIONS:
            found = [n for n in _names(ctx) if re.search(rf"{partition}-p", n)]
            if not found and listing is None:
                found = [p.name for p in work.glob(f"*{partition}-p*")]
            if listing is not None and found:
                listing.extract(ctx.tools.seven_zz, work, members=found)
            pat = sorted(work.glob(f"{partition}-p*"))
            if found and pat:
                pat[0].rename(work / f"{partition}.img")


@extractor(19, "terminal")
class SignedTerminal(Extractor):
    name = "signed"

    def detect(self, ctx: WorkContext) -> bool:
        return _detect_file_or_work(ctx, r"system-sign\.img", "system-sign.img")

    def extract(self, ctx: WorkContext) -> None:
        work = ctx.workdir
        listing = ctx.archive_listing
        if listing is not None:
            listing.extract_all(ctx.tools.seven_zz, work, flat=False)
        for partition in PARTITIONS:
            img = work / f"{partition}.img"
            if img.is_file():
                shutil.move(str(img), str(ctx.outdir / img.name))
        for p in list(work.glob("*/*-sign.img")):
            shutil.move(str(p), str(work / p.name))
        for p in list(work.iterdir()):
            if p.is_file() and "-sign.img" not in p.name:
                p.unlink(missing_ok=True)
        for p in list(work.glob("*-sign.img")):
            p.rename(work / (p.name[: -len("-sign.img")] + ".img"))
        for p in sorted(work.glob("*.img")):
            if not strip_signature(p, work / "x.img"):
                continue
            shutil.move(str(work / "x.img"), str(p))


def _strip_magic(img: Path) -> bytes:
    with img.open("rb") as fh:
        return fh.read(4)


def strip_signature(img: Path, out: Path) -> bool:
    """Strip SSSS/BFBF signed headers, streamed (never load the whole image)."""
    magic = _strip_magic(img)
    try:
        with img.open("rb") as fh:
            if magic == b"SSSS":
                header = fh.read(64)
                low = int.from_bytes(header[60:62], "little")
                high = int.from_bytes(header[62:64], "little")
                offset = 65536 * high + low
                fh.seek(64)
                with out.open("wb") as dst:
                    shutil.copyfileobj(fh, dst, length=offset)
                logger.info("Cleaning {} with SSSS header (offset {})", img.name, offset)
                return True
            if magic == b"BFBF":
                fh.seek(0x4040)
                with out.open("wb") as dst:
                    shutil.copyfileobj(fh, dst, length=1 << 20)
                logger.info("Cleaning {} with BFBF header", img.name)
                return True
    except OSError:
        return False
    out.unlink(missing_ok=True)
    return False


@extractor(20, "terminal")
class SuperTerminal(Extractor):
    name = "super"

    def detect(self, ctx: WorkContext) -> bool:
        return ctx.archive_listing is not None and ctx.archive_listing.has(r"super\.img")

    def extract(self, ctx: WorkContext) -> None:
        work = ctx.workdir
        listing = ctx.archive_listing
        if listing is None:
            return
        foundsupers = listing.matched_names(r"super\.img")
        by_basename: dict[str, int] = {}
        for n in foundsupers:
            by_basename[n.rsplit("/", 1)[-1]] = by_basename.get(n.rsplit("/", 1)[-1], 0) + 1
        if max(by_basename.values(), default=1) > 1:
            logger.info("Multiple super.img images detected")
            root_sup = next((n for n in foundsupers if "/" not in n), None)
            listing.extract(ctx.tools.seven_zz, work, members=[root_sup] if root_sup else foundsupers)
            sub_supers = [n for n in foundsupers if "/" in n]
            if sub_supers:
                listing.extract(ctx.tools.seven_zz, work, members=sub_supers, flat=False)
            extras = [p for p in work.rglob("super.img") if p.parent != work]
            superimage_extract(ctx, extras)
            prune_empty_dirs(work)
        else:
            listing.extract(ctx.tools.seven_zz, work, members=foundsupers or ["dummypartition"])
            chunks = _work_find(ctx, "*super*chunk*")
            if chunks and any("sparsechunk" in c.name for c in chunks):
                if merge_sparse_chunks(ctx.tools, chunks, work / "super.img.raw"):
                    for c in chunks:
                        c.unlink(missing_ok=True)
            superimage_extract(ctx)


@extractor(21, "terminal")
class SuperDirTerminal(Extractor):
    name = "superdir"

    def detect(self, ctx: WorkContext) -> bool:
        return len(_work_find(ctx, "super*.*img")) >= 1

    def extract(self, ctx: WorkContext) -> None:
        work = ctx.workdir
        listing = ctx.archive_listing
        if listing is not None:
            foundsupers = listing.matched_names(r"super.*img")
            listing.extract(ctx.tools.seven_zz, work, members=foundsupers or ["dummypartition"])
        splitsupers = [p for p in work.glob("super.*.img") if re.search(r"super\.[0-9].+\.img", p.name)]
        if splitsupers:
            logger.info("Creating super.img.raw ...")
            merge_sparse_chunks(ctx.tools, splitsupers, work / "super.img.raw")
            for s in splitsupers:
                s.unlink(missing_ok=True)
        chunks = [c for c in _work_find(ctx, "*super*chunk*") if "sparsechunk" in c.name]
        if chunks:
            logger.info("Creating super.img.raw ...")
            merge_sparse_chunks(ctx.tools, chunks, work / "super.img.raw")
            for c in chunks:
                c.unlink(missing_ok=True)
        superimage_extract(ctx)


@extractor(22, "terminal")
class Tarmd5Terminal(Extractor):
    name = "tarmd5"

    def detect(self, ctx: WorkContext) -> bool:
        if any(re.search(r"tar\.md5", n) and "AP_" in n for n in _names(ctx)):
            return True
        return bool(_work_find(ctx, "AP_*tar.md5"))

    def extract(self, ctx: WorkContext) -> None:
        work = ctx.workdir
        if ctx.archive_listing is not None:
            ctx.archive_listing.extract_all(ctx.tools.seven_zz, work, flat=True)
        for tar in sorted(work.glob("*.tar.md5")):
            if not tar.is_file():
                continue
            if not run(["tar", "-xf", str(tar)], cwd=work).ok:
                raise RuntimeError(f"tar extract failed: {tar.name}")
            tar.unlink(missing_ok=True)
        for lz4 in sorted(work.glob("*.lz4")):
            if not lz4.is_file():
                continue
            out = work / (lz4.name[: -len(".lz4")])
            with out.open("wb") as fh:
                res = run(["lz4", "-dc", str(lz4)], cwd=work, capture=True)
                fh.write(res.stdout)
            lz4.unlink(missing_ok=True)
        for ext4 in list(work.glob("*.ext4")):
            ext4.rename(work / ext4.name[: -len(".ext4")])
        if (work / "super.img").is_file():
            superimage_extract(ctx)
        if not (work / "system.img").exists():
            logger.error("tarmd5 extract failed: system.img missing")
            raise RuntimeError("Extract failed")


@extractor(23, "terminal")
class PayloadTerminal(Extractor):
    name = "payload"

    def detect(self, ctx: WorkContext) -> bool:
        return _detect_file_or_work(ctx, r"payload\.bin", "payload.bin")

    def extract(self, ctx: WorkContext) -> None:
        tool = ctx.tools["payload-dumper-go"]
        if tool is None:
            raise FileNotFoundError("payload-dumper-go missing (utils/bin)")
        cores = str(os.cpu_count() or 4)
        run([str(tool), "-c", cores, "-o", str(ctx.workdir), str(ctx.source)])


@extractor(24, "terminal")
class ArchiveTerminal(Extractor):
    name = "archive"

    def detect(self, ctx: WorkContext) -> bool:
        listing = ctx.archive_listing
        if listing is not None and listing.has(r"\.rar|\.zip|\.7z|\.tar$"):
            return True
        return any(_work_find(ctx, base) for base in ("*.rar", "*.zip", "*.7z", "*.tar"))

    def extract(self, ctx: WorkContext) -> Path | None:
        work = ctx.workdir
        listing = ctx.archive_listing
        if listing is not None:
            listing.extract_all(ctx.tools.seven_zz, work, flat=False)
        nested = [
            p
            for base in ("*.rar", "*.zip", "*.7z", "*.tar")
            for p in _work_find(ctx, base)
            if p.is_file() and p.stat().st_size > 300 * 1024 * 1024
        ]
        if not nested:
            return None
        ctx.inputdir.mkdir(parents=True, exist_ok=True)
        for p in list(ctx.inputdir.iterdir()):
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
        first = nested[0]
        shutil.move(str(first), str(ctx.inputdir / first.name))
        for p in list(work.iterdir()):
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink(missing_ok=True)
        logger.info("nested archive re-sourced -> {}", ctx.inputdir / first.name)
        return ctx.inputdir / first.name


@extractor(25, "terminal")
class UpdateAppTerminal(Extractor):
    name = "updateapp"

    def detect(self, ctx: WorkContext) -> bool:
        return _detect_file_or_work(ctx, r"UPDATE\.APP", "UPDATE.APP")

    def extract(self, ctx: WorkContext) -> None:
        work = ctx.workdir
        listing = ctx.archive_listing
        if listing is not None:
            listing.extract(ctx.tools.seven_zz, work, members=["UPDATE.APP"], flat=False)
        for p in list(work.rglob("UPDATE.APP")):
            shutil.move(str(p), str(work / "UPDATE.APP"))
        splituapp = ctx.tools["splituapp"]
        uapp = work / "UPDATE.APP"
        if splituapp is None or not uapp.is_file():
            return
        res = run(["python3", str(splituapp), "-f", str(uapp), "-l"], cwd=work, capture=True)
        if not res.ok:
            for partition in PARTITIONS:
                run(["python3", str(splituapp), "-f", str(uapp), "-l", partition], cwd=work, capture=True)
        output = work / "output"
        for p in list(output.rglob("*.img")) if output.is_dir() else []:
            shutil.move(str(p), str(work / p.name))
        supers = sorted(work.glob("super_*.img"))
        if supers or (work / "super.img").is_file():
            superimage_extract(ctx, supers)


@extractor(26, "terminal")
class RockchipTerminal(Extractor):
    name = "rockchip"

    def detect(self, ctx: WorkContext) -> bool:
        return _detect_file_or_work(ctx, r"rockchip", "rockchip")

    def extract(self, ctx: WorkContext) -> None:
        work = ctx.workdir
        rk = ctx.tools["rkImageMaker"]
        afp = ctx.tools["afptool"]
        if rk is None or afp is None:
            return
        run([str(rk), "-unpack", str(ctx.source), str(work)], cwd=work)
        run([str(afp), "-unpack", str((work / "firmware.img")), str(work)], cwd=work)
        image_super = work / "Image" / "super.img"
        if image_super.is_file():
            image_super.rename(work / "super.img")
            superimage_extract(ctx)
        for partition in PARTITIONS:
            for candidate in (work / "Image" / f"{partition}.img", work / f"{partition}.img"):
                if candidate.is_file():
                    shutil.move(str(candidate), str(ctx.outdir / f"{partition}.img"))
                    break


__all__ = [
    "ArchiveTerminal",
    "BinTerminal",
    "ChunkTerminal",
    "DatTerminal",
    "Nb0Terminal",
    "PacTerminal",
    "PayloadTerminal",
    "PsuffixTerminal",
    "QfilTerminal",
    "RawImageTerminal",
    "RockchipTerminal",
    "SignedTerminal",
    "SinTerminal",
    "SuperDirTerminal",
    "SuperTerminal",
    "Tarmd5Terminal",
    "UpdateAppTerminal",
]
