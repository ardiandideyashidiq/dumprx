"""Tests for terminal extractors (raw partition chain, order 10+)."""

from __future__ import annotations

import io
import tarfile
from types import SimpleNamespace

import pytest

from dumprx.config import build_config
from dumprx.extractors import ClassifyError, WorkContext, classify
from dumprx.extractors.terminals import _concat_dat_parts, strip_signature


def _ctx(tmp_path, name="source.bin", listing=None) -> WorkContext:
    src = tmp_path / name
    src.write_bytes(b"seed")
    cfg = build_config(project_dir=tmp_path, outdir=tmp_path)
    paths = type(cfg.paths)(
        project_dir=tmp_path,
        inputdir=tmp_path / "input",
        utilsdir=tmp_path / "utils",
        outdir=tmp_path / "out",
        workdir=tmp_path / "out" / "tmp",
    )
    cfg = cfg.with_paths(paths)
    (tmp_path / "out" / "tmp").mkdir(parents=True, exist_ok=True)
    (tmp_path / "utils" / "bin").mkdir(parents=True, exist_ok=True)
    return WorkContext(
        source=src,
        outdir=paths.outdir,
        workdir=paths.workdir,
        config=cfg,
        archive_listing=listing,
    )


class FakeArchive:
    """Listing that records extract() calls and stubs 7zz-like writes."""

    def __init__(self, names, files=None):
        self.names = list(names)
        self.files = files or {}

    @property
    def member_names(self):
        return self.names

    def entries(self):
        return iter(self.names)

    def has(self, pattern):
        import re

        return any(re.search(pattern, n) for n in self.names)

    def matched_names(self, pattern):
        import re

        return [n for n in self.names if re.search(pattern, n)]

    def extract(self, seven_zz, dest, members=None, flat=True):
        import re

        dest.mkdir(parents=True, exist_ok=True)
        for member in members or self.names:
            for name in self.matched_names(re.escape(member).replace(r"\*", ".*")):
                if name in self.files:
                    out_name = name.rsplit("/", 1)[-1] if flat else name
                    out = dest / out_name
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(self.files[name])

    def extract_all(self, seven_zz, dest, flat=False):
        for name in self.names:
            if name in self.files:
                out = dest / (name.rsplit("/", 1)[-1] if flat else name)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(self.files[name])


def _stub(utils, rel):
    p = utils / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# stub\n")


# --- routing fidelity ---


@pytest.mark.parametrize(
    "names,expected",
    [
        (["system.new.dat"], "dat"),
        (["rawprogram0.xml"], "qfil"),
        (["TA-1000.nb0"], "nb0"),
        (["system.img.chunk.1"], "chunk"),
        (["firmware/system_new.img"], "rawimage"),
        (["system.sin"], "sin"),
        (["SPD_1516.pac"], "pac"),
        (["system.bin"], "bin"),
        (["system-p.img"], "psuffix"),
        (["system-sign.img"], "signed"),
        (["super.img"], "super"),
        (["AP_COM8N_WW_user.tar.md5"], "tarmd5"),
        (["payload.bin"], "payload"),
        (["bundle.zip"], "archive"),
        (["UPDATE.APP"], "updateapp"),
        (["rockchip_binary"], "rockchip"),
    ],
)
def test_terminal_classify_bash_order(tmp_path, names, expected):
    listing = FakeArchive(names)
    assert classify(_ctx(tmp_path, "bundle.zip", listing)).name == expected


def test_chunk_detect_skips_so_lines(tmp_path):
    listing = FakeArchive(["system.img.chunk.1", "splitbedism.system.chunk.so"])
    assert classify(_ctx(tmp_path, "bundle.zip", listing)).name == "chunk"


def test_chunk_detect_only_so_lines_falls_through(tmp_path):
    listing = FakeArchive(["vndsystem.chunk.so"])
    with pytest.raises(ClassifyError):
        classify(_ctx(tmp_path, "bundle.zip", listing))


def test_chunk_detect_directory_source(tmp_path):
    ctx = _ctx(tmp_path, "dir")
    ctx.source.unlink()
    ctx.source.mkdir(exist_ok=True)
    (ctx.workdir / "system.img.chunk.0").write_bytes(b"c")
    assert classify(ctx).name == "chunk"


def test_superdir_detects_dirsource_super(tmp_path):
    ctx = _ctx(tmp_path, "dir")
    ctx.source.unlink()
    ctx.source.mkdir(exist_ok=True)
    (ctx.workdir / "super.img").write_bytes(b"s")
    assert classify(ctx).name == "superdir"


# --- dat ---


def test_concat_dat_parts_is_numeric_and_streams(tmp_path):
    base = tmp_path / "system.new.dat"
    base.write_bytes(b"head")
    files = [("system.new.dat.3", b"three"), ("system.new.dat.1", b"one"), ("system.new.dat.10", b"ten")]
    for name, data in files:
        (tmp_path / name).write_bytes(data)
    _concat_dat_parts(base)
    assert list(base.parent.glob("system.new.dat.[0-9]*")) == []
    assert base.read_bytes() == b"head" + b"one" + b"three" + b"ten"


def test_dat_extract_runs_sdat2img_and_cleans(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, "ota.zip", FakeArchive(["system.new.dat", "system.transfer.list"]))
    _stub(ctx.config.paths.utilsdir, "sdat2img.py")
    (ctx.workdir / "system.new.dat").write_bytes(b"dat")
    (ctx.workdir / "system.transfer.list").write_bytes(b"t")
    (ctx.workdir / "system.new.dat.0").write_bytes(b"tail")
    (ctx.workdir / "system.new.dat.1").write_bytes(b"")

    def fake_run(argv, **kw):
        if argv[0] == "python3":
            (ctx.outdir / "system.img").write_bytes(b"made")
        return SimpleNamespace(ok=True, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("dumprx.extractors.terminals.run", fake_run)
    classify(ctx).extract(ctx)
    assert (ctx.outdir / "system.img").read_bytes() == b"made"
    assert not (ctx.workdir / "system.new.dat").exists()
    assert not (ctx.workdir / "system.transfer.list").exists()


# --- signed header stripping ---


def test_strip_signature_ssss_offset_math(tmp_path):
    img = tmp_path / "system-sign.img"
    header = bytearray(64)
    header[:4] = b"SSSS"
    header[60:62] = (44).to_bytes(2, "little")
    body = b"PAYLOAD-PAYLOAD-PAYLOAD-PAYLOAD"
    img.write_bytes(bytes(header) + body)
    assert strip_signature(img, tmp_path / "x.img")
    assert (tmp_path / "x.img").read_bytes() == body[:44]


def test_strip_signature_bfbf_skips_0x4040(tmp_path):
    img = tmp_path / "system-sign.img"
    img.write_bytes(b"BFBF" + b"\x00" * (0x4040 - 4) + b"raw")
    out = tmp_path / "x.img"
    assert strip_signature(img, out)
    assert out.read_bytes() == b"raw"


def test_strip_signature_unknown_touches_nothing(tmp_path):
    img = tmp_path / "system-sign.img"
    img.write_bytes(b"plain")
    out = tmp_path / "x.img"
    assert not strip_signature(img, out)
    assert not out.exists()


# --- tarmd5 ---


def test_tarmd5_extract_tar_lz4_ext4(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, "dir")
    ctx.source.unlink()
    ctx.source.mkdir(exist_ok=True)
    work = ctx.workdir
    tar = work / "AP_x.tar.md5"
    with tarfile.open(tar, "w") as tf:
        data = b"sys"
        info = tarfile.TarInfo("system.img")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    (work / "vendor.img.ext4").write_bytes(b"v")
    (work / "boot.lz4").write_bytes(b"\x04\x22\x4d\x18V")

    def fake_run(argv, **kw):
        if argv[0] == "tar":
            with tarfile.open(str(argv[-1]), "r:*") as tf:
                for m in tf.getmembers():
                    (ctx.workdir / m.name).write_bytes(tf.extractfile(m).read())
            return SimpleNamespace(ok=True, returncode=0, stdout=b"", stderr=b"")
        if argv[0] == "lz4":
            return SimpleNamespace(ok=True, returncode=0, stdout=b"VER", stderr=b"")
        return SimpleNamespace(ok=False, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("dumprx.extractors.terminals.run", fake_run)
    classify(ctx).extract(ctx)
    assert (ctx.workdir / "system.img").read_bytes() == b"sys"
    assert not tar.exists()
    assert (ctx.workdir / "vendor.img").exists()  # .ext4 -> .img
    assert (ctx.workdir / "boot").read_bytes() == b"VER"  # lz4 -dc
