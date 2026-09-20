"""Tests for the property engine: propper cascade, derive(), board-info."""

from __future__ import annotations

from pathlib import Path

from dumprx.props.board_info import board_info_lines
from dumprx.props.models import derive
from dumprx.props.propper import PropStore, build_prop_files, expand_locs, parse_prop_file


def write(root: Path, rel: str, content: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_parse_prop_file_basic(tmp_path):
    f = tmp_path / "build.prop"
    f.write_text("ro.foo=bar\n# comment\nro.empty=\nro.space= a value \n", encoding="utf-8")
    data = parse_prop_file(f)
    assert data["ro.foo"] == "bar"
    assert data["ro.space"] == "a value"
    assert "ro.empty" in data
    assert "ro.comment" not in data


def test_expand_locs_braces():
    dirs = expand_locs("{system,system/system}")
    assert str(dirs[0]) == "system"
    assert str(dirs[1]) == "system/system"


def test_build_prop_files_maxdepth2(tmp_path):
    write(tmp_path, "system/build.prop", "a=1")
    write(tmp_path, "system/etc/build.prop", "b=2")
    write(tmp_path, "system/deep/deep/build.prop", "c=3")
    files = build_prop_files(tmp_path, [tmp_path / "system"])
    rel = {str(p.relative_to(tmp_path)) for p in files}
    assert "system/build.prop" in rel
    assert "system/etc/build.prop" in rel
    assert "system/deep/deep/build.prop" not in rel


def test_prop_get_cascade_and_fallthrough(tmp_path):
    write(tmp_path, "vendor/build.prop", "ro.product.brand=Realme\nro.x=vendorval")
    write(tmp_path, "system/build.prop", "ro.product.brand=SystemBrand\nro.product.device=sysdev")
    store = PropStore(tmp_path)
    assert store.get("ro.product.brand", ["{system,system/system,vendor}"]) == "SystemBrand"
    assert store.get("ro.only.in.vendor", ["{system,system/system,vendor}"]) is None
    # cascade order: vendor listed last, but system wins by loc order here
    cand = store.get("ro.product.device", ["{vendor,system,system/system}"])
    assert cand == "sysdev"


FIXTURE = {
    "system/system/build.prop": (
        "ro.build.flavor=bazel-f\n"
        "ro.build.version.release=14\n"
        "ro.build.id=UP1A.231005.007\n"
        "ro.build.tags=release-keys\n"
        "ro.board.platform=mt6789\n"
        "ro.product.manufacturer=Realme\n"
        "ro.product.brand=realme\n"
        "ro.build.fingerprint=realme/RMXPI/device:14/UP1A.231005.007/xid\n"
        "ro.build.description=RMX-user 14 UP1A.231005.007 xid release-keys\n"
        "ro.build.version.incremental=RMX001\n"
        "ro.product.device=devicex\n"
        "ro.build.version.security_patch=2024-06-01\n"
        "ro.product.cpu.abilist=arm64-v8a\n"
        "ro.sf.lcd_density=440\n"
        "ro.build.ab_update=true\n"
        "ro.treble.enabled=true\n"
        "ro.build.version.ota=RMXPI_14_001\n"
    ),
    "vendor/build.prop": (
        "ro.vendor.mediatek.platform=MT6789V\n"
        "ro.vendor.board.platform=mt6789v\n"
    ),
    "my_manifest/build.prop": (
        "ro.product.odm.brand=Realme\n"
        "ro.product.odm.model=RMXPI_DeviceX\n"
        "ro.vendor.oplus.market.name=Realme GT\n"
    ),
    "tr_manifest/build.prop": (
        "ro.build.date=Fri Jun 07 2024\n"
    ),
    "product/build.prop": (
        "ro.tranos.version=8.1.0\n"
        "ro.product.product.tran.device.name.default=Transsion-X\n"
        "ro.build.display.id=RMXPI14_Q.1\n"
    ),
    "boot/kernel": b"LZ4 magic - not real\nLinux version 5.15.60-android13-4-00002-gabc123abc123-dirty (build@server) #1 SMP PREEMPT\n".decode(),
}


def test_derive_full_cascade(tmp_path):
    for rel, body in FIXTURE.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            target.write_bytes(body)
        else:
            target.write_text(body, encoding="utf-8")
    store = PropStore(tmp_path)
    info = derive(tmp_path, store)

    assert info.flavor == "bazel-f"
    assert info.release == "14"
    assert info.id == "UP1A.231005.007"
    assert info.platform == "MT6789V"  # vendor override wins
    assert info.manufacturer == "Realme"
    assert info.brand == "realme"
    assert info.codename == "RMXPI_DeviceX"  # my_manifest odm.model override
    assert info.fingerprint == "realme/RMXPI/device:14/UP1A.231005.007/xid"
    assert info.incremental == "RMX001"
    assert info.description == "RMX-user 14 UP1A.231005.007 xid release-keys"
    assert info.abilist == "arm64-v8a"
    assert info.density == "440"
    assert info.is_ab == "true"
    assert info.treble_support == "true"
    assert info.sec_patch == "2024-06-01"
    assert info.otaver == "RMXPI_14_001"
    # fingerprint exists -> otaver does NOT set branch; xosid wins later
    assert info.transname == "Transsion-X"
    assert info.xosver == "8.1.0"
    assert info.xosid == "RMXPI14_Q.1"
    assert info.branch == "RMXPI14_Q.1"
    assert info.opname == "Realme GT"
    assert info.date == "Fri Jun 07 2024"
    assert info.repo == "Realme/RMXPI_DeviceX"
    assert info.kernel_version == "5.15.60-android13-4-00002-gabc123abc123-dirty"


def test_board_info_from_modem_tz(tmp_path):
    modem = tmp_path / "modem"
    modem.mkdir()
    (modem / "modem.bin").write_bytes(
        b"META\x00QC_IMAGE_VERSION_STRING=MPSS.HP.1.2.3\x00META2"
    )
    tzdir = tmp_path / "tz.bin"
    tzdir.mkdir()
    (tzdir / "tz.img").write_bytes(b"QC_IMAGE_VERSION_STRING=MPSS.99.88\n")
    lines = board_info_lines(tmp_path)
    assert lines
    assert "require version-baseband=1.2.3" in lines  # MPSS. stripped, cut -c4
    assert any("require version-trustzone" in line for line in lines)


def test_board_info_empty(tmp_path):
    assert board_info_lines(tmp_path) == []


def test_xiaomi_and_transsion_name_fields(tmp_path):
    write(tmp_path, "odm/etc/build.prop", "ro.product.odm.marketname=POCO 5 Pro\nro.product.odm.marketname=notalllowercase\nro.product.odm.marketname=abc\n")
    write(tmp_path, "vendor/odm/etc/build.prop", "ro.product.odm.marketname=POCO 5 Pro\n")
    write(tmp_path, "odm/etc/goldwatermark/configs/TranssionWM.json", '{"TEXT_BRAND_NAME": "Transsion S1"}')
    write(tmp_path, "product/build.prop", "")
    write(tmp_path, "system/build.prop", "")
    store = PropStore(tmp_path)
    info = derive(tmp_path, store)
    assert info.xiaominame == "POCO 5 Pro"  # all-lowercase values filtered
    assert info.transname == "Transsion S1"


def test_expand_locs_unbraced_comma():
    dirs = expand_locs("vendor,system,system/system,odm")
    assert [str(d) for d in dirs] == ["vendor", "system", "system/system", "odm"]


def test_derive_density_from_vendor_and_date_fallback(tmp_path):
    write(tmp_path, "vendor/build.prop", "ro.sf.lcd_density=320\nro.product.vendor.manufacturer=ITEL\nro.product.vendor.device=itel-P661N\n")
    write(tmp_path, "system/system/build.prop", "ro.build.date=Wed Jul 23 05:12:24 CST 2025\n")
    store = PropStore(tmp_path)
    info = derive(tmp_path, store)
    assert info.density == "320"
    assert info.date == "Wed Jul 23 05:12:24 CST 2025"

