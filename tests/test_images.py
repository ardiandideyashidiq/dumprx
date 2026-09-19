"""Tests for the image layer: header strip math, sparse merge."""

from __future__ import annotations

import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from dumprx.images import (
    merge_sparse_chunks,
    strip_signed_header,
    super_to_raw,
    to_raw_image,
)
from dumprx.tools import Tools


def _fake_tools(tmp_path, monkeypatch, fail: bool = False):
    """Minimal fake Tools whose simg2img writes dst with marked header."""
    (tmp_path / "bin").mkdir(exist_ok=True)
    (tmp_path / "bin" / "simg2img").write_text("#!/bin/sh\nsleep 0\n")

    def fake_run(argv, **kwargs):
        # argv = [simg2img, src..., dst]  -> copy last src to dst
        if fail:
            return SimpleNamespace(ok=False, returncode=1)
        shutil = __import__("shutil")
        shutil.copyfile(argv[-2], argv[-1])
        return SimpleNamespace(ok=True, returncode=0)

    monkeypatch.setattr("dumprx.images.run", fake_run)
    return Tools(utilsdir=tmp_path)


def _build_signed(tmp_path, magic: str, pat_pos: int) -> Path:
    img = tmp_path / "signed.img"
    size = pat_pos + 5000
    with img.open("wb") as fh:
        fh.write(magic.encode() + b"\x00" * max(0, _PAT_PAD - len(magic)))
        fh.seek(pat_pos)
        fh.write(b"\x53\xEF")
        fh.write(b"TAIL-DATA")
        fh.truncate(size)
    return img


_PAT_PAD = 4096


def _pattern_marker(img: Path, offset: int) -> bytes:
    with img.open("rb") as fh:
        fh.seek(offset)
        return fh.read(9)


def test_no_magic_no_strip(tmp_path, monkeypatch):
    img = tmp_path / "plain.img"
    img.write_bytes(b"QUALCOMM-RAW\x00" * 100)
    out = tmp_path / "stripped.img"
    assert strip_signed_header(_fake_tools(tmp_path, monkeypatch), img, out) is False
    assert not out.exists()


def test_moto_strip_offset_math(tmp_path, monkeypatch):
    pat_pos = 6000 + 1080
    img = _build_signed(tmp_path, "MOTO-HEADER", pat_pos)
    out = tmp_path / "stripped.img"
    assert strip_signed_header(_fake_tools(tmp_path, monkeypatch), img, out) is True
    assert out.read_bytes() == img.read_bytes()[6000:]
    assert out.read_bytes()[1080:1091] == b"\x53\xEFTAIL-DATA"


def test_moto_special_offset_compensation(tmp_path, monkeypatch):
    # offset computed == 128055 triggers 131072 adjustment (bash quirk)
    img = tmp_path / "moto.img"
    with img.open("wb") as fh:
        fh.write(b"MOTO" + b"\x00" * 131072)
        fh.seek(131072 + 1080)
        fh.write(b"\x53\xEF")
    out = tmp_path / "stripped.img"
    assert strip_signed_header(_fake_tools(tmp_path, monkeypatch), img, out) is True
    assert out.read_bytes() == img.read_bytes()[131072:]


def test_asus_strip_no_adjust(tmp_path, monkeypatch):
    # find pos P; offset = P - 1080; no compensation quirk for ASUS
    pat_pos = 5000 + 1080
    img = _build_signed(tmp_path, "ASUS-HEAD", pat_pos)
    out = tmp_path / "a.img"
    assert strip_signed_header(_fake_tools(tmp_path, monkeypatch), img, out) is True
    assert out.read_bytes() == img.read_bytes()[5000:]


def test_simg2img_and_fallback(tmp_path, monkeypatch):
    src = tmp_path / "sparse.img"
    src.write_text("sparse-data")
    dst = tmp_path / "raw.img"

    tools = _fake_tools(tmp_path, monkeypatch, fail=False)
    assert to_raw_image(tools, src, dst) is True
    assert dst.read_text() == "sparse-data"

    fail_tools = _fake_tools(tmp_path, monkeypatch, fail=True)
    dst2 = tmp_path / "raw2.img"
    assert to_raw_image(fail_tools, src, dst2) is True  # copy fallback
    assert dst2.read_text() == "sparse-data"


def test_merge_sparse_chunks(tmp_path, monkeypatch):
    a = tmp_path / "system-sparsechunk0"
    b = tmp_path / "system-sparsechunk1"
    a.write_text("A")
    b.write_text("B")
    dst = tmp_path / "system.img.raw"
    assert merge_sparse_chunks(_fake_tools(tmp_path, monkeypatch), [a, b], dst) is True
    assert dst.read_text() == "B"  # fake simg2img copies last src


def test_super_to_raw_merge(tmp_path, monkeypatch):
    sup = tmp_path / "super.img"
    extra = tmp_path / "extra.img"
    sup.write_text("SUPER")
    extra.write_text("EXTRA")
    tools = _fake_tools(tmp_path, monkeypatch)
    assert super_to_raw(tools, sup, extra) is True
    assert sup.with_name("super.img.raw").read_text() == "EXTRA"
    assert not sup.exists()
    assert not extra.exists()


def _real_tools():
    repo_root = Path(__file__).resolve().parents[1]
    return Tools(utilsdir=repo_root / "utils")


def _make_sparse(raw: bytes, dst: Path) -> None:
    blk, total = 4096, len(raw) // 4096
    hdr = struct.pack("<IHHHHIIII", 0xED26FF3A, 1, 0, 28, 12, blk, total, 1, 0)
    chk = struct.pack("<HHII", 0xCAC1, 0, total, 12 + len(raw))
    dst.write_bytes(hdr + chk + raw)


@pytest.mark.skipif(
    not Path(__file__).resolve().parents[1].joinpath("utils/bin/simg2img").exists(),
    reason="vendored simg2img not present",
)
def test_real_simg2img_roundtrip(tmp_path):
    raw = bytes(i % 251 for i in range(4 * 1024 * 1024))
    sparse = tmp_path / "system-sparse.img"
    _make_sparse(raw, sparse)
    out = tmp_path / "system.raw.img"
    tools = _real_tools()
    assert to_raw_image(tools, sparse, out) is True
    assert out.read_bytes() == raw
