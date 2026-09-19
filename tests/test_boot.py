"""Tests for boot-family extraction orchestration (runs are faked)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dumprx.boot import extract_boot_family
from dumprx.tools import Tools


def _tools(tmp_path) -> Tools:
    (tmp_path / "bin").mkdir(exist_ok=True)
    for name in ("unpackboot.sh", "extract-ikconfig", "avbtool.py", "dtc"):
        (tmp_path / name).write_text("#!/bin/sh\n")
    (tmp_path / "vmlinux-to-elf").mkdir(exist_ok=True)
    (tmp_path / "vmlinux-to-elf" / "vmlinux-to-elf").write_text("#!/bin/sh\n")
    (tmp_path / "vmlinux-to-elf" / "kallsyms-finder").write_text("#!/bin/sh\n")
    return Tools(utilsdir=tmp_path)


def _patch(monkeypatch, resp):
    monkeypatch.setattr("dumprx.boot.run", lambda argv, **kw: resp(list(argv), **kw))


def _ok(stdout=b"", returncode=0):
    return SimpleNamespace(
        ok=returncode == 0, returncode=returncode, stdout=stdout, stderr=b"", elapsed_ms=0
    )


def test_boot_full_chain(tmp_path, monkeypatch):
    (tmp_path / "boot.img").write_bytes(b"boot")
    calls: list[list[str]] = []

    def resp(argv, **kw):
        calls.append(argv)
        if len(argv) > 1 and "unpackboot" in argv[1]:
            Path(argv[3]).mkdir(parents=True, exist_ok=True)
        if len(argv) > 1 and "ikconfig" in argv[1]:
            return _ok(stdout=b"CONFIG_X=y")
        if len(argv) > 1 and "avbtool" in argv[1]:
            return _ok(stdout=b"AVB-DATA")
        if "extract-dtb" in argv:
            out_dir = Path(argv[argv.index("-o") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "img1.dtb").write_bytes(b"\xd0\x0d\xfe\xed")
        return _ok()

    _patch(monkeypatch, resp)
    tools = _tools(tmp_path)
    extract_boot_family(tmp_path, tools)
    joined = " ".join(" ".join(c) for c in calls)
    assert "bootimg" in joined and "bootdts" in joined
    assert (tmp_path / "boot" / "avb.txt").read_text() == "AVB-DATA"
    assert (tmp_path / "bootRE" / "ikconfig").read_text() == "CONFIG_X=y"
    assert "boot.elf" in joined
    assert "img1.dts" in joined  # dtc conversion ran


def test_vendor_boot_kallsyms_source(tmp_path, monkeypatch):
    (tmp_path / "boot.img").write_bytes(b"b")
    (tmp_path / "vendor_boot.img").write_bytes(b"vb")
    calls: list[list[str]] = []

    def resp(argv, **kw):
        calls.append(argv)
        if len(argv) > 1 and "unpackboot" in argv[1]:
            unpack_to = Path(argv[3])
            unpack_to.mkdir(parents=True, exist_ok=True)
            (unpack_to / "kernel").write_bytes(b"k")  # unpacked kernel exists
        return _ok()

    _patch(monkeypatch, resp)
    extract_boot_family(tmp_path, _tools(tmp_path))
    calls_flat = " ".join(" ".join(c) for c in calls)
    # vendor_boot present -> kernel_kallsyms.txt from unpacked boot/kernel
    assert (tmp_path / "bootRE" / "kernel_kallsyms.txt").exists()
    assert "boot_kallsyms.txt" not in calls_flat
    assert "vendor_boot.elf" in calls_flat


def test_no_boot_images_noops(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    _patch(monkeypatch, lambda argv, **kw: (calls.append(argv) or _ok()))
    extract_boot_family(tmp_path, _tools(tmp_path))
    assert calls == []
