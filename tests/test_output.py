"""Group 11: readme.py (dump card + tg.html) and twrp.py + notify.py."""

from __future__ import annotations

from pathlib import Path

from dumprx.config import Secrets, build_config
from dumprx.notify import send_tg_html
from dumprx.props.models import FirmwareInfo
from dumprx.readme import build_tg_html, render_readme, write_readme


def _info(**kw):
    base = dict(
        description="flavor 13 RELEASE tags",
        manufacturer="Infinix",
        codename="X6878",
        platform="mt6789",
        opchipset="Helio G99",
        id="TP1A.220624.014",
        release="13",
        kernel_version="5.10.136-android13-4-00001-gabcdef",
        transname="Infinix NOTE 30 Pro",
        fingerprint="Infinix/X6878/Infinix-X6878:13/TP1A.220624.014/221126V2212:user/release-keys",
        sec_patch="2022-11-05",
        is_ab="true",
        treble_support="true",
        density="393",
        abilist="arm64-v8a,armeabi-v7a,armeabi",
        date="Thu Nov 17 12:24:27 KST 2022",
        xiaominame="",
    )
    return FirmwareInfo(**{**base, **kw})


def test_render_readme_matches_fixture(tmp_path):
    info = _info()
    write_readme(tmp_path, info)
    text = (tmp_path / "README.md").read_text()
    assert text.startswith("## FIRMWARE DUMP\n### flavor 13 RELEASE tags\n")
    assert "- Fingerprint: Infinix/X6878/Infinix-X6878:13/TP1A.220624.014/221126V2212:user/release-keys" in text
    assert "- Kernel version: 5.10.136-android13-4-00001-gabcdef" in text
    assert "- Platform: mt6789 (Helio G99)" in text  # opchipset variant
    assert "- Brand: Infinix" in text
    assert "- Model: X6878" in text


def test_render_readme_skips_empty_fields():
    info = _info(platform="", transname="", kernel_version="", opchipset="")
    lines = "\n".join(render_readme(info))
    assert "- Platform:" not in lines
    assert "Transsion name" not in lines
    assert "- Android build: TP1A.220624.014" in lines


def test_render_readme_tranchipset_takes_priority():
    info = _info(tranchipset="octa-core", opchipset="Helio G99")
    lines = "\n".join(render_readme(info))
    assert "- Platform: mt6789 (octa-core)" in lines


def test_build_tg_html_blockquote_layout():
    info = _info()
    html = build_tg_html(info, repo_url="https://x/y", repo_label="Tree")
    assert html.startswith("<blockquote><b>FIRMWARE DUMP INFO</b></blockquote>")
    assert "\n<b>Model: <code>X6878</code></b>" in html
    assert '\n<a href="https://x/y">Tree</a>' in html
    assert "Transsion name" in html
    assert "Xiaomi name" not in html  # empty field omitted


def test_send_tg_html_no_token_skips():
    cfg = build_config(mode="local")
    assert send_tg_html("x", cfg) is False


def test_send_tg_html_failure_tolerated(monkeypatch):
    cfg = build_config(mode="local").with_secrets(Secrets(tg_token="tok", tg_chat="@c"))
    calls = []

    def fake_run(args, timeout=None):
        calls.append(args)
        class R:
            ok = False
            returncode = 7
            out = stdout = stderr = ""
        return R()

    import dumprx.notify as notify

    monkeypatch.setattr(notify, "run", fake_run)
    assert send_tg_html("some text", cfg) is False
    assert any("api.telegram.org/bot" in a[2] for a in calls)
    assert len(calls) == 1  # failure not retried


def test_twrp_generate_legacy_prefers_recovery_then_boot(monkeypatch, tmp_path):
    from dumprx import twrp
    from dumprx.config import Paths

    cfg = build_config(mode="local").with_paths(
        Paths(
            project_dir=tmp_path,
            inputdir=tmp_path / "input",
            utilsdir=tmp_path,
            outdir=tmp_path,
        )
    )
    (tmp_path / "recovery.img").write_bytes(b"\x00" * 8)
    (tmp_path / "boot.img").write_bytes(b"\x00" * 8)
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "unpack_bootimg.py").touch()
    images_seen = []

    class StubTree:
        def __init__(self, **kwargs):
            images_seen.extend(kwargs["images"])

        def dump_to_folder(self, out: Path) -> None:
            out.mkdir(parents=True)

    monkeypatch.setattr(twrp, "DeviceTree", StubTree)
    monkeypatch.setattr(twrp, "_fetch_wiki_readme", lambda out: None)
    twrp.generate(cfg)
    assert images_seen == [tmp_path / "recovery.img", tmp_path / "boot.img"]
    assert (tmp_path / "twrp-device-tree").is_dir()


def test_twrp_generate_gki_picks_vendor_and_init_boot(monkeypatch, tmp_path):
    from dumprx import twrp
    from dumprx.config import Paths

    cfg = build_config(mode="local").with_paths(
        Paths(
            project_dir=tmp_path,
            inputdir=tmp_path / "input",
            utilsdir=tmp_path,
            outdir=tmp_path,
        )
    )
    (tmp_path / "vendor_boot.img").write_bytes(b"\x00" * 8)
    (tmp_path / "init_boot.img").write_bytes(b"\x00" * 8)
    (tmp_path / "boot.img").write_bytes(b"\x00" * 8)
    (tmp_path / "dtbo.img").write_bytes(b"\x00" * 8)
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "unpack_bootimg.py").touch()
    received = {}

    class StubTree:
        def __init__(self, **kwargs):
            received.update(kwargs)

        def dump_to_folder(self, out: Path) -> None:
            out.mkdir(parents=True)

    monkeypatch.setattr(twrp, "DeviceTree", StubTree)
    monkeypatch.setattr(twrp, "_fetch_wiki_readme", lambda out: None)
    twrp.generate(cfg)
    assert received["images"] == [
        tmp_path / "vendor_boot.img",
        tmp_path / "init_boot.img",
        tmp_path / "boot.img",
    ]
    assert received["dtbo"] == tmp_path / "dtbo.img"


def test_twrp_generate_skips_without_any_image(monkeypatch, tmp_path):
    from dumprx import twrp
    from dumprx.config import Paths

    cfg = build_config(mode="local").with_paths(
        Paths(
            project_dir=tmp_path,
            inputdir=tmp_path / "input",
            utilsdir=tmp_path,
            outdir=tmp_path,
        )
    )

    def fail(*_args, **_kwargs):
        raise AssertionError("DeviceTree must not be called")

    monkeypatch.setattr(twrp, "DeviceTree", fail)
    twrp.generate(cfg)
    assert not (tmp_path / "twrp-device-tree").exists()


def test_twrp_generate_failure_is_best_effort(monkeypatch, tmp_path):
    from dumprx import twrp
    from dumprx.config import Paths

    cfg = build_config(mode="local").with_paths(
        Paths(
            project_dir=tmp_path,
            inputdir=tmp_path / "input",
            utilsdir=tmp_path,
            outdir=tmp_path,
        )
    )
    (tmp_path / "boot.img").write_bytes(b"\x00" * 8)
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "unpack_bootimg.py").touch()

    class BrokenTree:
        def __init__(self, **kwargs):
            pass

        def dump_to_folder(self, out):
            raise AssertionError("no ramdisk")

    monkeypatch.setattr(twrp, "DeviceTree", BrokenTree)
    twrp.generate(cfg)
    assert not (tmp_path / "twrp-device-tree").exists()


def test_twrpdtgen_gki_header_v4_skips_kernel_in_prebuilt(tmp_path):
    from twrpdtgen.image_info import ImageInfo
    from twrpdtgen.templates import render_template

    kernel_file = tmp_path / "kernel"
    kernel_file.write_bytes(b"KERNEL")
    dtb_file = tmp_path / "dtb"
    dtb_file.write_bytes(b"DTB")
    dtbo_file = tmp_path / "dtbo"
    dtbo_file.write_bytes(b"DTBO")

    info = ImageInfo(
        header_version="4",
        vendor_boot_size=1024,
        ramdisk_compression="lz4",
        kernel=kernel_file,
        dtb=dtb_file,
        dtbo=dtbo_file,
    )
    assert info.is_header_v4_gki is True

    render_template(
        tmp_path,
        "BoardConfig.mk",
        device_info=type(
            "DI",
            (),
            {
                "manufacturer": "itel",
                "codename": "P661N",
                "device_is_ab": False,
                "arch": type(
                    "Arch",
                    (),
                    {
                        "arch": "arm64",
                        "arch_variant": "armv8-a",
                        "cpu_abi": "arm64-v8a",
                        "cpu_abi2": "",
                        "bitness": 64,
                    },
                )(),
                "second_arch": None,
                "cpu_variant": "generic",
                "second_cpu_variant": None,
                "device_uses_updatable_apex": False,
                "bootloader_board_name": "P661N",
                "screen_density": "320",
                "use_vulkan": False,
                "device_uses_system_as_root": False,
            },
        )(),
        fstab=type("FST", (), {"get_ab_partitions_models": lambda self: []})(),
        image_info=info,
        current_year="2026",
        version="1.0.0",
    )
    rendered = (tmp_path / "BoardConfig.mk").read_text()
    assert "BOARD_RAMDISK_USE_LZ4 := true" in rendered
    assert "TARGET_NO_KERNEL := true" in rendered
    assert "TARGET_PREBUILT_DTB := $(DEVICE_PATH)/prebuilt/dtb.img" in rendered
    assert "TARGET_FORCE_PREBUILT_KERNEL" not in rendered
    assert "TARGET_PREBUILT_KERNEL" not in rendered

