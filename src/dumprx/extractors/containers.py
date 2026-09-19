"""Container extractors: ozip, ops (in-archive + direct), ofp, tgz.

Each port 1:1 from dumper.sh. Containers return the next Source (`Path`) for
the stage queue: a decrypted zip/dir in INPUTDIR. Shared quirks preserved:
`INPUTDIR` is cleared before each inner reload, deployable via input dir.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from loguru import logger

from dumprx.extractors.base import Extractor, WorkContext, extractor
from dumprx.process import run


def _stage_input(ctx: WorkContext) -> Path:
    """Copy current source into the work dir, mirroring `stage_input_file`."""
    staged = ctx.workdir / ctx.source.name
    shutil.copyfile(ctx.source, staged)
    return staged


def _reset_inputdir(ctx: WorkContext) -> None:
    inp = ctx.inputdir
    if inp.exists():
        for p in inp.iterdir():
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
    inp.mkdir(parents=True, exist_ok=True)


def _clear_workdir(ctx: WorkContext) -> None:
    for p in ctx.workdir.iterdir():
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()


def _head(source: Path, length: int = 12) -> bytes:
    try:
        with source.open("rb") as fh:
            return fh.read(length)
    except OSError:
        return b""


def _extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _move_contents(src_dir: Path, dst_dir: Path) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    if not src_dir.is_dir():
        return
    for p in src_dir.iterdir():
        shutil.move(str(p), str(dst_dir / p.name))


@extractor(1, "container")
class OzipExtractor(Extractor):
    name = "ozip"

    def detect(self, ctx: WorkContext) -> bool:
        return _head(ctx.source) == b"OPPOENCRYPT!" or _extension(ctx.source.name) == "ozip"

    def extract(self, ctx: WorkContext) -> Path | None:
        staged = _stage_input(ctx)
        ozipdecrypt = ctx.tools["ozipdecrypt"]
        if ozipdecrypt is None:
            raise FileNotFoundError("ozipdecrypt.py missing (clone oppo_ozip_decrypt)")
        logger.info("Decrypting ozip and making a zip...")
        run(["python3", str(ozipdecrypt), str(staged)], cwd=ctx.workdir)
        _reset_inputdir(ctx)
        next_source = ctx.inputdir
        zipped = ctx.workdir / f"{staged.stem}.zip"
        if zipped.is_file():
            shutil.move(str(zipped), str(ctx.inputdir / zipped.name))
            next_source = ctx.inputdir / zipped.name
        elif (ctx.workdir / "out").is_dir():
            _move_contents(ctx.workdir / "out", ctx.inputdir)
        _clear_workdir(ctx)
        logger.info("ozip decrypted -> {}", next_source)
        return next_source


class _NestedOppoExtractor(Extractor):
    """Shared logic for an archive that contains a single .ops/.ofp payload."""

    suffix = ".ops"
    name = "ops-in-archive"

    def detect(self, ctx: WorkContext) -> bool:
        listing = ctx.archive_listing
        if listing is None:
            return False
        return any(m.endswith(self.suffix) for m in listing.member_names)

    def extract(self, ctx: WorkContext) -> Path | None:
        listing = ctx.archive_listing
        member = next(m for m in listing.member_names if m.endswith(self.suffix))
        zz = ctx.tools.seven_zz
        log = ctx.workdir / "zip.log"
        with log.open("ab") as fh:
            res = run(
                [zz, "e", "-y", "--", str(ctx.source), member, f"*/{member}"],
                cwd=ctx.workdir,
                capture=True,
            )
            fh.write(res.stdout)
        _reset_inputdir(ctx)
        basename = member.rsplit("/", 1)[-1]
        shutil.move(str(ctx.workdir / basename), str(ctx.inputdir / basename))
        next_source = ctx.inputdir / basename
        logger.info("{} payload extracted -> {}", self.name, next_source)
        return next_source


@extractor(2, "container")
class OpsInArchive(_NestedOppoExtractor):
    suffix = ".ops"
    name = "ops-in-archive"


@extractor(3, "container")
class OpsDirectExtractor(Extractor):
    name = "ops"

    def detect(self, ctx: WorkContext) -> bool:
        return _extension(ctx.source.name) == "ops"

    def extract(self, ctx: WorkContext) -> Path | None:
        staged = _stage_input(ctx)
        opsdecrypt = ctx.tools["opscrypto"]
        if opsdecrypt is None:
            raise FileNotFoundError("opscrypto.py missing (clone oppo_decrypt)")
        logger.info("Decrypting ops & extracting...")
        run(["python3", str(opsdecrypt), "decrypt", str(staged)], cwd=ctx.workdir)
        _reset_inputdir(ctx)
        _move_contents(ctx.workdir / "extract", ctx.inputdir)
        _clear_workdir(ctx)
        next_source = ctx.inputdir
        zipped = ctx.inputdir / f"{staged.stem}.zip"
        if zipped.exists():
            next_source = zipped
        logger.info("ops decrypted -> {}", next_source)
        return next_source


@extractor(4, "container")
class OfpInArchive(_NestedOppoExtractor):
    suffix = ".ofp"
    name = "ofp-in-archive"


@extractor(5, "container")
class OfpDirectExtractor(Extractor):
    name = "ofp"

    def detect(self, ctx: WorkContext) -> bool:
        return _extension(ctx.source.name) == "ofp"

    def extract(self, ctx: WorkContext) -> Path | None:
        staged = _stage_input(ctx)
        out_dir = ctx.workdir / "out"
        out_dir.mkdir(exist_ok=True)
        ofp_qc = ctx.tools["ofp_qc_decrypt"]
        ofp_mtk = ctx.tools["ofp_mtk_decrypt"]
        if ofp_qc is None or ofp_mtk is None:
            raise FileNotFoundError("ofp decryptors missing (clone oppo_decrypt)")
        logger.info("Decrypting ofp & extracting...")
        run(["python3", str(ofp_qc), str(staged), str(out_dir)], cwd=ctx.workdir)
        if not _ofp_ok(out_dir):
            run(["python3", str(ofp_mtk), str(staged), str(out_dir)], cwd=ctx.workdir)
            if not _ofp_ok(out_dir):
                raise RuntimeError("ofp decryption error (QC and MTK both failed)")
        _reset_inputdir(ctx)
        _move_contents(out_dir, ctx.inputdir)
        _clear_workdir(ctx)
        next_source = ctx.inputdir
        logger.info("ofp decrypted -> {}", next_source)
        return next_source


def _ofp_ok(out_dir: Path) -> bool:
    return (out_dir / "boot.img").is_file() and (out_dir / "userdata.img").is_file()


@extractor(6, "container")
class TgzExtractor(Extractor):
    name = "tgz"

    def detect(self, ctx: WorkContext) -> bool:
        name = ctx.source.name
        return name.endswith(".tgz") or name.endswith(".tar.gz")

    def extract(self, ctx: WorkContext) -> Path | None:
        ctx.inputdir.mkdir(parents=True, exist_ok=True)
        source = ctx.source
        if isinstance(source, Path) and not source.is_file():
            return ctx.source
        run(
            ["tar", "xzvf", str(source), "-C", str(ctx.inputdir), "--transform=s/.*\\///"],
            timeout=3600,
        )
        # Delete empty folder leftovers
        for d in sorted((p for p in ctx.inputdir.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass
        _clear_workdir(ctx)
        logger.info("tgz extracted -> {}", ctx.inputdir)
        return ctx.inputdir


@extractor(7, "container")
class KdzExtractor(Extractor):
    name = "kdz"

    def detect(self, ctx: WorkContext) -> bool:
        name = ctx.source.name
        return name.lower().endswith(".kdz") or _extension(name) == "kdz"

    def extract(self, ctx: WorkContext) -> Path | None:
        work = ctx.workdir
        shutil.copy2(ctx.source, work / ctx.source.name)
        unkdz = ctx.tools["unkdz"]
        undz = ctx.tools["undz"]
        if unkdz is None or undz is None:
            raise FileNotFoundError("unkdz.py/undz.py missing (kdztools)")
        logger.info("Extracting all partitions as individual images.")
        run(["python3", str(unkdz), "-f", ctx.source.name, "-x", "-o", "./"], cwd=work)
        dz_file = next((p for p in work.glob("*.dz")), None)
        if dz_file is None:
            raise RuntimeError(f"no .dz produced by unkdz for {ctx.source.name}")
        run(["python3", str(undz), "-f", dz_file.name, "-s", "-o", "./"], cwd=work)
        (work / ctx.source.name).unlink(missing_ok=True)
        dz_file.unlink(missing_ok=True)
        _rename_images(work)
        logger.info("kdz extracted -> {}", work)
        return work


def _rename_images(work: Path) -> None:
    """Mirror the *.image -> *.img, *_a.img -> *.img, *_b.img removals."""
    for i in list(work.glob("*.image")):
        i.rename(work / (i.name[:-6] + ".img"))
    for i in list(work.glob("*_a.img")):
        i.rename(work / (i.name[: -len("_a.img")] + ".img"))
    for i in work.glob("*_b.img"):
        i.unlink(missing_ok=True)


@extractor(8, "container")
class RuuExtractor(Extractor):
    name = "ruu"

    def detect(self, ctx: WorkContext) -> bool:
        name = ctx.source.name.lower()
        return (name.startswith("ruu_") and name.endswith(".exe")) or _extension(name) == "exe"

    def extract(self, ctx: WorkContext) -> Path | None:
        work = ctx.workdir
        shutil.copy2(ctx.source, work / ctx.source.name)
        ruudecrypt = ctx.tools["ruu_decrypt"]
        if ruudecrypt is None:
            raise FileNotFoundError("RUU_Decrypt_Tool missing")
        logger.info("Extracting system and firmware partitions...")
        run([str(ruudecrypt), "-s", ctx.source.name], cwd=work)
        run([str(ruudecrypt), "-f", ctx.source.name], cwd=work)
        out_dirs = work.glob("OUT*")
        for outdir in out_dirs:
            if not outdir.is_dir():
                continue
            for img in outdir.glob("*.img"):
                shutil.move(str(img), str(work / img.name))
        logger.info("ruu extracted -> {}", work)
        return work


@extractor(9, "container")
class AmlExtractor(Extractor):
    name = "aml"

    def detect(self, ctx: WorkContext) -> bool:
        listing = ctx.archive_listing
        if listing is None:
            return False
        return any("aml" in m.lower() for m in listing.member_names)

    def extract(self, ctx: WorkContext) -> Path | None:
        work = ctx.workdir
        source = ctx.source
        shutil.copy2(source, work / source.name)
        zz = ctx.tools.seven_zz
        run([zz, "e", "-y", str(source)], cwd=work, capture=True)
        aml_files = [p for p in work.glob("*aml*.img")]
        aml_extract = ctx.tools["aml_extract"]
        if aml_extract is None:
            raise FileNotFoundError("aml-upgrade-package-extract missing")
        if aml_files:
            run([str(aml_extract), *(str(p) for p in aml_files)], cwd=work)
        for p in list(work.glob("*.PARTITION")):
            p.rename(work / (p.name[: -len(".PARTITION")] + ".img"))
        for p in list(work.glob("*_aml_dtb.img")):
            p.rename(work / (p.name[: -len("_aml_dtb.img")] + "_dtb.img"))
        for p in list(work.glob("*_a.img")):
            p.rename(work / (p.name[: -len("_a.img")] + ".img"))
        from dumprx.extractors.super import superimage_extract

        if (work / "super.img").is_file():
            superimage_extract(ctx)
        from dumprx.config import PARTITIONS

        for partition in PARTITIONS:
            img = work / f"{partition}.img"
            if img.exists():
                shutil.move(str(img), str(ctx.outdir / img.name))
        logger.info("aml extracted -> {}", ctx.outdir)
        return ctx.outdir


__all__ = [
    "OfpDirectExtractor",
    "OpsDirectExtractor",
    "OzipExtractor",
    "TgzExtractor",
    "_NestedOppoExtractor",
]
