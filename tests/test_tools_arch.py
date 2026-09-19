"""Tests for tool discovery and the 7zz archive layer."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dumprx.arch import Archive
from dumprx.tools import Tools, ensure_runtime_clones

BIN_OUT = SimpleNamespace(ok=True, returncode=0, stdout=b"", stderr=b"")


def test_tools_resolve_vendored(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "simg2img").write_text("x")
    tools = Tools(utilsdir=tmp_path)
    assert tools.resolve("simg2img") == tmp_path / "bin" / "simg2img"


def test_tools_missing_returns_none(tmp_path):
    tools = Tools(utilsdir=tmp_path)
    assert tools.resolve("simg2img") is None
    with pytest.raises(FileNotFoundError):
        tools.require("simg2img")


def test_tools_seven_zz_fallback_order(tmp_path, monkeypatch):
    (tmp_path / "bin").mkdir()
    vendored = tmp_path / "bin" / "7zz"
    vendored.write_text("x")
    monkeypatch.setattr("dumprx.tools.run", lambda *a, **k: BIN_OUT)
    monkeypatch.setattr("dumprx.process.which", lambda name: None)
    tools = Tools(utilsdir=tmp_path)
    assert tools.seven_zz == str(vendored)
    monkeypatch.setattr("dumprx.process.which", lambda name: "/usr/bin/7zz")
    assert tools.seven_zz == "/usr/bin/7zz"


def test_ensure_runtime_clones(tmp_path, monkeypatch):
    for slug in ("oppo_ozip_decrypt", "vmlinux-to-elf"):
        (tmp_path / slug).mkdir(parents=True)
        (tmp_path / slug / ".git").mkdir()

    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return BIN_OUT

    monkeypatch.setattr("dumprx.tools.run", fake_run)
    ensure_runtime_clones(tmp_path)
    clones = [c for c in calls if c[0] == "git" and c[1] == "clone"]
    pulls = [c for c in calls if c[0] == "git" and c[1] == "-C"]
    assert len(clones) == 3  # 5 total - 2 already present
    assert len(pulls) == 2


def run_with_stdout(monkeypatch, text: str):
    def fake_run(argv, **kwargs):
        return SimpleNamespace(
            ok=True, returncode=0, stdout=text.encode(), stderr=b""
        )

    monkeypatch.setattr("dumprx.arch.run", fake_run)


def test_listing_file_backed(tmp_path, monkeypatch):
    listing_file = tmp_path / "list.txt"
    run_with_stdout(monkeypatch, "2023-01-01 00:00:00 a system.img\n2023 another dir/vendor.img\n")

    arc = Archive(tmp_path / "fw.zip", listing_file=listing_file)
    arc.write_listing("7zz")
    assert listing_file.is_file()

    arc2 = Archive(tmp_path / "fw.zip", listing_file=listing_file)
    assert arc2.member_names() == ["system.img", "dir/vendor.img"]
    assert arc2.has("vendor")
    assert arc2.matched_names("system") == ["system.img"]


def test_extract_tolerant_missing_members(tmp_path, monkeypatch):
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return SimpleNamespace(ok=True, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("dumprx.arch.run", fake_run)
    arc = Archive(tmp_path / "fw.zip")
    ok = arc.extract("7zz", tmp_path / "dest", members=["system.img", "foo.bar"], flat=True)
    assert ok
    argv = captured["argv"]
    assert argv[0] == "7zz" and "e" in argv
    assert argv[-1] == "dummypartition"
    assert "system.img" in argv and "*/system.img" in argv


def test_extract_all_uses_x(tmp_path, monkeypatch):
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return BIN_OUT

    monkeypatch.setattr("dumprx.arch.run", fake_run)
    Archive(tmp_path / "fw.zip").extract_all("7zz", tmp_path / "dest")
    assert "x" in captured["argv"]
