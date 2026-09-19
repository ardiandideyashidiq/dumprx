"""Tests for dumprx.aospdtgen (vendored aospdtgen DeviceTree wrapper)."""

from __future__ import annotations

from pathlib import Path

from dumprx.config import build_config


def _cfg(tmp_path: Path):
    from dumprx.config import Paths

    return build_config(mode="local").with_paths(
        Paths(
            project_dir=tmp_path,
            inputdir=tmp_path / "input",
            utilsdir=tmp_path,
            outdir=tmp_path,
        )
    )


def _stub_images(tmp_path: Path) -> None:
    """Create the minimal OUTDIR shape the wrapper checks before running."""
    (tmp_path / "boot.img").write_bytes(b"\x00" * 8)
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "unpack_bootimg.py").touch()


def test_generate_writes_aosp_tree_at_device_path(monkeypatch, tmp_path):
    from dumprx import aospdtgen

    _stub_images(tmp_path)

    received = {}

    class StubTree:
        def __init__(self, path, **kwargs):
            received["path"] = path
            received["kwargs"] = kwargs
            self.device_info = type("DI", (), {"manufacturer": "itel", "codename": "FULL-64-ARMV82"})()

        def dump_to_folder(self, target: Path) -> None:
            received["target"] = target
            target.mkdir(parents=True)

        def cleanup(self) -> None:
            received["cleaned"] = True

    monkeypatch.setattr(aospdtgen, "DeviceTree", StubTree)
    aospdtgen.generate(_cfg(tmp_path))
    assert received["path"] == tmp_path
    assert received["target"] == (
        tmp_path / "aosp-device-tree" / "device" / "itel" / "FULL-64-ARMV82"
    )
    assert received["cleaned"] is True


def test_generate_skips_without_boot_image(monkeypatch, tmp_path):
    from dumprx import aospdtgen

    def fail(*_args, **_kwargs):
        raise AssertionError("DeviceTree must not be called")

    monkeypatch.setattr(aospdtgen, "DeviceTree", fail)
    aospdtgen.generate(_cfg(tmp_path))
    assert not (tmp_path / "aosp-device-tree").exists()


def test_generate_skips_without_unpack_tool(monkeypatch, tmp_path):
    from dumprx import aospdtgen

    (tmp_path / "boot.img").write_bytes(b"\x00" * 8)

    def fail(*_args, **_kwargs):
        raise AssertionError("DeviceTree must not be called")

    monkeypatch.setattr(aospdtgen, "DeviceTree", fail)
    aospdtgen.generate(_cfg(tmp_path))
    assert not (tmp_path / "aosp-device-tree").exists()


def test_generate_failure_is_best_effort(monkeypatch, tmp_path):
    from dumprx import aospdtgen

    _stub_images(tmp_path)

    class BrokenTree:
        def __init__(self, **kwargs):
            raise AssertionError("No fstab found")

    monkeypatch.setattr(aospdtgen, "DeviceTree", BrokenTree)
    aospdtgen.generate(_cfg(tmp_path))
    assert not (tmp_path / "aosp-device-tree").exists()
