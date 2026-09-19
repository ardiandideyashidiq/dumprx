"""Tests for the extractor registry and container decoding."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from dumprx.config import build_config
from dumprx.extractors import ClassifyError, WorkContext, classify, load_extractors


@pytest.fixture(autouse=True)
def _registered():
    load_extractors()


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


def _res():
    return SimpleNamespace(ok=True, returncode=0, stdout=b"", stderr=b"", elapsed_ms=0)


def _stub(utils, rel):
    p = utils / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# stub\n")


def test_classify_first_match_contains_wins(tmp_path):
    # zip with embedded ".ops": ops-in-archive (an early container) wins
    listing = SimpleNamespace(member_names=["ota/1.ops"])
    ex_name = classify(_ctx(tmp_path, "bundle.zip", listing)).name
    assert ex_name == "ops-in-archive"


def test_classify_no_match_lists_candidates(tmp_path):
    with pytest.raises(ClassifyError) as exc:
        classify(_ctx(tmp_path, "mystery.xyz"))
    assert "mystery.xyz" in str(exc.value)
    assert "ozip" in str(exc.value)


def test_ozip_magic_detects(tmp_path):
    ctx = _ctx(tmp_path, "f.bin")
    ctx.source.write_bytes(b"OPPOENCRYPT!")
    assert classify(ctx).name == "ozip"


def test_ops_direct_detects(tmp_path):
    assert classify(_ctx(tmp_path, "f.ops")).name == "ops"


def test_ofp_in_archive_detects(tmp_path):
    listing = SimpleNamespace(member_names=["x/1.ofp"])
    assert classify(_ctx(tmp_path, "w.zip", listing)).name == "ofp-in-archive"


def test_tgz_detects(tmp_path):
    assert classify(_ctx(tmp_path, "f.tar.gz")).name == "tgz"


def test_ozip_extract_requeues_zip(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, "realme.ota.ozip")
    _stub(ctx.config.paths.utilsdir, "oppo_ozip_decrypt/ozipdecrypt.py")

    def fake_run(argv, **kw):
        if argv[0] == "python3":
            (kw.get("cwd", ctx.workdir) / "realme.ota.zip").write_bytes(b"PK\x03\x04")
        return _res()

    monkeypatch.setattr("dumprx.extractors.containers.run", fake_run)
    next_source = classify(ctx).extract(ctx)
    assert next_source is not None
    assert next_source.name == "realme.ota.zip"
    assert next_source.exists()
    assert (ctx.workdir / "realme.ota.zip").exists() is False


def test_ops_direct_extract_requeues(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, "f.ops")
    _stub(ctx.config.paths.utilsdir, "oppo_decrypt/opscrypto.py")
    monkeypatch.setattr(
        "dumprx.extractors.containers.run",
        lambda argv, **kw: (
            (kw.get("cwd", ctx.workdir) / "extract").mkdir(exist_ok=True)
            or (kw.get("cwd", ctx.workdir) / "extract" / "payload.bin").write_bytes(b"p")
            or _res()
        ),
    )
    classify(ctx).extract(ctx)
    assert (ctx.inputdir / "payload.bin").exists()


def test_ofp_direct_extract_requeues(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, "f.ofp")
    utils = ctx.config.paths.utilsdir
    _stub(utils, "oppo_decrypt/ofp_qc_decrypt.py")
    _stub(utils, "oppo_decrypt/ofp_mtk_decrypt.py")

    def fake_run(argv, **kw):
        if "ofp" in argv[1]:
            out = Path(argv[-1])
            out.mkdir(parents=True, exist_ok=True)
            (out / "boot.img").write_bytes(b"b")
            (out / "userdata.img").write_bytes(b"u")
        return _res()

    monkeypatch.setattr("dumprx.extractors.containers.run", fake_run)
    next_source = classify(ctx).extract(ctx)
    assert (ctx.inputdir / "boot.img").exists()
    assert (ctx.inputdir / "userdata.img").exists()
    assert next_source == ctx.inputdir


def test_tgz_extract_flattens_into_inputdir(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, "firmware.tgz")
    ctx.source.unlink()
    src = ctx.source
    with tarfile.open(src, "w:gz") as tf:
        data = b"raw-system"
        info = tarfile.TarInfo("dir/system.img")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))

    def fake_run(argv, **kw):
        # emulate `tar xzf ... --transform=s/.*\\///` -> flat extraction
        with tarfile.open(src, "r:*") as tf:
            for member in tf.getmembers():
                if member.isfile():
                    (ctx.inputdir / member.name.rsplit("/", 1)[-1]).write_bytes(
                        tf.extractfile(member).read()
                    )
        return _res()

    monkeypatch.setattr("dumprx.extractors.containers.run", fake_run)
    next_source = classify(ctx).extract(ctx)
    assert next_source == ctx.inputdir
    assert (ctx.inputdir / "system.img").read_bytes() == b"raw-system"


def test_kdz_extract_renames_images(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, "G900H.kdz")
    utils = ctx.config.paths.utilsdir
    _stub(utils, "kdztools/unkdz.py")
    _stub(utils, "kdztools/undz.py")
    calls: list[list[str]] = []

    def fake_run(argv, **kw):
        calls.append(argv)
        if "unkdz" in argv[1]:
            (ctx.workdir / "payload.dz").write_bytes(b"dz")
        if "undz" in argv[1]:
            (ctx.workdir / "system.image").write_bytes(b"i")
            (ctx.workdir / "product_a.img").write_bytes(b"i")
            (ctx.workdir / "vendor_b.img").write_bytes(b"i")
            (ctx.workdir / "boot.img").write_bytes(b"i")
        return _res()

    monkeypatch.setattr("dumprx.extractors.containers.run", fake_run)
    next_source = classify(ctx).extract(ctx)
    assert next_source == ctx.workdir
    assert (ctx.workdir / "system.img").exists()  # .image -> .img
    assert (ctx.workdir / "product.img").exists()  # _a.img -> .img
    assert not (ctx.workdir / "vendor_b.img").exists()  # _b.img removed
    assert not (ctx.workdir / "payload.dz").exists()
    assert not (ctx.workdir / ctx.source.name).exists()


def test_ruu_extract_moves_outdir_imgs(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, "ruu_RUU.zip.exe")
    _stub(ctx.config.paths.utilsdir, "RUU_Decrypt_Tool")

    def fake_run(argv, **kw):
        out = ctx.workdir / "OUT_1"
        out.mkdir(exist_ok=True)
        (out / "system.img").write_bytes(b"s")
        return _res()

    monkeypatch.setattr("dumprx.extractors.containers.run", fake_run)
    next_source = classify(ctx).extract(ctx)
    assert (ctx.workdir / "system.img").exists()  # hoisted out of OUT_1
    assert next_source == ctx.workdir


def test_aml_extract_renames_and_moves_to_outdir(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, "update.aml.zip", listing=SimpleNamespace(member_names=["update_aml.img"]))
    utils = ctx.config.paths.utilsdir
    _stub(utils, "aml-upgrade-package-extract")

    def fake_run(argv, **kw):
        if "7zz" in Path(argv[0]).name:
            (ctx.workdir / "update_aml.img").write_bytes(b"u")  # 7zz e output
        if "aml-upgrade" in str(argv[0]):
            (ctx.workdir / "boot_a.img").write_bytes(b"b")
            (ctx.workdir / "app_aml_dtb.img").write_bytes(b"d")
            (ctx.workdir / "vbmeta.PARTITION").write_bytes(b"v")
            (ctx.workdir / "system.img").write_bytes(b"s")
            (ctx.workdir / "super.img").write_bytes(b"sp")
        return _res()

    monkeypatch.setattr("dumprx.extractors.containers.run", fake_run)
    next_source = classify(ctx).extract(ctx)
    assert next_source == ctx.outdir
    assert (ctx.outdir / "boot.img").exists()  # _a.img -> .img
    assert (ctx.workdir / "app_dtb.img").exists()  # _aml_dtb -> dtb, stays (non-partition)
    assert (ctx.outdir / "vbmeta.img").exists()  # .PARTITION -> .img
    assert (ctx.outdir / "system.img").exists()
