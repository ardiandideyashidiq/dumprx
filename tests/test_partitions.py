"""Tests for partition extraction and super-chunk identification."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dumprx.partitions import (
    extract_euclid_imgs,
    extract_fs_partition,
    extract_fs_partitions,
    identify_super_chunks,
)
from dumprx.tools import Tools


def _tools(tmp_path) -> Tools:
    (tmp_path / "bin").mkdir(exist_ok=True)
    (tmp_path / "bin" / "fsck.erofs").write_text("#!/bin/sh\n")
    (tmp_path / "bin" / "7zz").write_text("#!/bin/sh\n")
    return Tools(utilsdir=tmp_path)


def _res(ok: bool, **kw):
    base = dict(ok=ok, returncode=0 if ok else 1, stdout=b"", stderr=b"", elapsed_ms=0)
    base.update(kw)
    return SimpleNamespace(**base)


def _patch_run(monkeypatch, responder):
    monkeypatch.setattr("dumprx.partitions.run", lambda argv, **kwargs: responder(list(argv)))
    return lambda argv, **kwargs: responder(list(argv))


def test_fsck_success_removes_img(tmp_path, monkeypatch):
    img = tmp_path / "system.img"
    img.write_bytes(b"erofs")
    calls: list[list[str]] = []
    _patch_run(monkeypatch, lambda argv: (calls.append(argv) or _res(True)))
    assert extract_fs_partition(tmp_path, "system", _tools(tmp_path)) is True
    assert not img.exists()
    assert f"--extract={tmp_path}/system" in calls[0]


def test_modem_exempt_keeps_img(tmp_path, monkeypatch):
    img = tmp_path / "modem.img"
    img.write_bytes(b"raw-modem")
    _patch_run(monkeypatch, lambda argv: _res(False))
    assert extract_fs_partition(tmp_path, "modem", _tools(tmp_path)) is False
    assert img.exists()  # never 7zz'd, never deleted


def test_7zz_fallback_on_fsck_fail(tmp_path, monkeypatch):
    img = tmp_path / "vendor.img"
    img.write_bytes(b"v")
    calls: list[list[str]] = []
    _patch_run(monkeypatch, lambda argv: (calls.append(argv), _res(False if len(calls) == 1 else True))[1])
    assert extract_fs_partition(tmp_path, "vendor", _tools(tmp_path)) is True
    assert not img.exists()
    assert "7zz" in calls[1][0]


def test_parallel_skips_boot_family(tmp_path, monkeypatch):
    for name in ("system", "vendor", "boot", "recovery"):
        (tmp_path / f"{name}.img").write_bytes(b"x")
    _patch_run(monkeypatch, lambda argv: _res(True))
    extract_fs_partitions(tmp_path, ["system", "vendor", "boot", "recovery"], _tools(tmp_path))
    # system/vendor imgs removed (erofs ok); boot/recovery skipped, img kept
    assert not (tmp_path / "system.img").exists()
    assert (tmp_path / "boot.img").exists()
    assert (tmp_path / "recovery.img").exists()


def test_identify_vendor_dlkm_chunk(tmp_path, monkeypatch):
    (tmp_path / "super_2.img").write_text("x")

    def responder(argv):
        argv_s = " ".join(map(str, argv))
        if "--extract=" in argv_s:
            temp = Path(argv[1].split("=")[1])
            modules = temp / "lib" / "modules"
            modules.mkdir(parents=True)
            (modules / "android-5.15").mkdir()
        return _res(True)

    _patch_run(monkeypatch, responder)
    ids = identify_super_chunks(tmp_path, _tools(tmp_path))
    assert ids
    assert (tmp_path / "system_dlkm").is_dir()


def test_identify_duplicate_claim(tmp_path, monkeypatch):
    (tmp_path / "super_2.img").write_text("x")
    (tmp_path / "super_3.img").write_text("y")

    def responder(argv):
        argv_s = " ".join(map(str, argv))
        if "--extract=" in argv_s:
            temp = Path(argv[1].split("=")[1])
            (temp / "build.prop").write_text("ro.product.odm.brand=X\n")
            (temp / "etc").mkdir(exist_ok=True)  # avoid the tr_manifest branch
            (temp / "etc" / "unused").write_text("")
        return _res(True)

    _patch_run(monkeypatch, responder)
    identify_super_chunks(tmp_path, _tools(tmp_path))
    assert (tmp_path / "odm").is_dir()
    assert (tmp_path / "odm_2").is_dir()


def test_euclid_extract(tmp_path, monkeypatch):
    euclid = tmp_path / "vendor" / "euclid"
    euclid.mkdir(parents=True)
    (euclid / "system.img").write_text("img")
    calls: list[list[str]] = []

    def responder(argv):
        calls.append(argv)
        if "euclid" in str(argv[0]) or "7zz" in argv[0].replace("\\", "/").split("/")[-1]:
            src = Path(argv[2])
            target = src.with_suffix("")
            target.mkdir(exist_ok=True)
        return _res(True)

    _patch_run(monkeypatch, responder)
    extract_euclid_imgs(tmp_path, _tools(tmp_path))
    assert (euclid / "system").is_dir()
    assert not (euclid / "system.img").exists()
    assert "7zz" in calls[0][0]
