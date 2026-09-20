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
            self.device_info = type("DI", (), {"manufacturer": "itel", "codename": "P661N"})()

        def dump_to_folder(self, target: Path) -> None:
            received["target"] = target
            target.mkdir(parents=True)

        def cleanup(self) -> None:
            received["cleaned"] = True

    monkeypatch.setattr(aospdtgen, "DeviceTree", StubTree)
    info = type("FI", (), {"codename": "P661N", "manufacturer": "itel"})()
    aospdtgen.generate(_cfg(tmp_path), info=info)
    assert received["path"] == tmp_path
    assert received["kwargs"]["firmware_info"] == info
    assert received["target"] == (
        tmp_path / "aosp-device-tree" / "device" / "itel" / "P661N"
    )
    assert received["cleaned"] is True


def test_device_tree_firmware_info_overrides_codename(tmp_path):
    from sebaubuntu_libs.libandroid.props import BuildProp

    from aospdtgen.device_tree import DeviceTree

    class DummyPartition:
        def __init__(self, name):
            self.model = type("M", (), {"name": name, "group": "treble", "proprietary_files_prefix": Path(name)})()
            self.path = tmp_path / name
            self.path.mkdir(parents=True, exist_ok=True)
            self.files = []
            self.build_prop = BuildProp()

        def fill_fstab_entry(self, fstab):
            pass

    # Setup minimal partition directory structure
    vendor_etc = tmp_path / "vendor" / "etc"
    vendor_etc.mkdir(parents=True, exist_ok=True)
    (vendor_etc / "fstab.mt6833").write_text("/dev/block/by-name/boot /boot emmc defaults defaults\n")

    info = type(
        "FI",
        (),
        {
            "codename": "P661N",
            "manufacturer": "itel",
            "brand": "Itel",
            "model": "itel P55 5G",
            "fingerprint": "Itel/P661N-GL/itel-P661N:13/TP1A.220624.014/250723V1644:user/release-keys",
            "description": "sys_tssi_64_armv82_itel-user 13 release-keys",
            "sec_patch": "2025-07-05",
            "density": "320",
            "platform": "MT6833",
        },
    )()

    class StubPartitions:
        def __init__(self, path):
            self.system = DummyPartition("system")
            prop_file = tmp_path / "system" / "build.prop"
            prop_file.write_text(
                "ro.product.system.device=FULL-64-ARMV82\n"
                "ro.product.system.manufacturer=itel\n"
                "ro.system.build.version.release=13\n"
                "ro.system.build.version.sdk=33\n"
                "ro.system.build.version.security_patch=2025-07-05\n"
                "ro.bionic.arch=arm64\n"
                "ro.bionic.cpu_variant=generic\n"
                "ro.bionic.2nd_arch=arm\n"
                "ro.bionic.2nd_cpu_variant=generic\n"
                "ro.bootimage.build.fingerprint=Itel/P661N-GL/itel-P661N:13/TP1A.220624.014/250723V1644:user/release-keys\n"
                "ro.boot.bootloader=P661N\n"
                "ro.product.board=P661N\n"
                "ro.product.first_api_level=33\n"
                "ro.build.version.security_patch=2025-07-05\n"
                "ro.board.platform=mt6833\n"
            )
            self.system.build_prop.import_props(prop_file)
            self.vendor = DummyPartition("vendor")
            self.vendor.files = [vendor_etc / "fstab.mt6833"]

        def get_all_partitions(self):
            return [self.system, self.vendor]

    import aospdtgen.device_tree as dt_mod
    orig_parts = dt_mod.Partitions
    orig_bc = dt_mod.BootConfiguration
    try:
        dt_mod.Partitions = StubPartitions
        dt_mod.BootConfiguration = lambda *a, **k: type("BC", (), {"recovery_image_info": None, "boot_image_info": type("BI", (), {"ramdisk": None})()})()
        dt = DeviceTree(tmp_path, no_proprietary_files=True, firmware_info=info)
        assert dt.device_info.codename == "P661N"
        assert dt.device_info.manufacturer == "itel"
        assert dt.device_info.platform == "mt6833"
        assert dt.device_info.screen_density == "320"
    finally:
        dt_mod.Partitions = orig_parts
        dt_mod.BootConfiguration = orig_bc


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


def test_is_blob_allowed():
    from aospdtgen.proprietary_files.ignore import is_blob_allowed

    assert is_blob_allowed(Path("bin/sh")) is False
    assert is_blob_allowed(Path("bin/custom_service")) is True
    assert is_blob_allowed(Path("lib/libc.so")) is False
    assert is_blob_allowed(Path("lib/libcustom.so")) is True
    assert is_blob_allowed(Path("etc/selinux/plat_sepolicy.cil")) is False


def test_unpack_cache_reuses_existing(tmp_path):
    from twrpdtgen.image_info import _UNPACK_CACHE, ImageInfo, _unpack_one

    image = tmp_path / "boot.img"
    image.write_bytes(b"\x00" * 32)
    outdir = tmp_path / "boot_unpacked"
    outdir.mkdir()

    cache_key = (image.resolve(), outdir.resolve())
    fake_info = ImageInfo(header_version="4", base_address="0x40078000")
    _UNPACK_CACHE[cache_key] = (fake_info, {"--header_version": "4"})

    info, pairs = _unpack_one(image, outdir, tool=Path("/nonexistent"))
    assert info.header_version == "4"
    assert info.base_address == "0x40078000"
    assert pairs["--header_version"] == "4"

