"""Firmware metadata model: the full property-derivation cascade from dumper.sh.

`derive()` reproduces every prop_get / prop_override / grep fallback in
dumper.sh lines ~1161-1360, first-match-wins in the exact original order.
"""

from __future__ import annotations

import gzip
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from dumprx.props.propper import PropStore, expand_glob_files, grep_value

_SYS_LOCS = ["{system,system/system,vendor}"]
_VENDOR_LOCS = ["vendor"]
_SYS_ONLY_LOCS = ["{system,system/system}"]
_PRODUCT_LOCS = ["product"]
_TR_LOCS = ["tr_manifest"]


def _clean(value: str | None) -> str:
    return value.strip() if value else ""


@dataclass
class FirmwareInfo:
    """All metadata surfaced in README, branch naming, and Telegram."""

    flavor: str = ""
    release: str = ""
    id: str = ""
    tags: str = ""
    platform: str = ""
    manufacturer: str = ""
    fingerprint: str = ""
    brand: str = ""
    codename: str = ""
    description: str = ""
    incremental: str = ""
    abilist: str = ""
    locale: str = "undefined"
    density: str = "undefined"
    is_ab: str = "false"
    treble_support: str = "false"
    otaver: str = ""
    transname: str = ""
    osver: str = ""
    xosver: str = ""
    sec_patch: str = ""
    xosid: str = ""
    tranchipset: str = ""
    opchipset: str = ""
    xiaominame: str = ""
    motoname: str = ""
    opname: str = ""
    date: str = ""
    kernel_version: str = ""
    branch: str = ""
    repo: str = ""

    extra: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for key, value in self.__dataclass_fields__.items():
            if key in ("extra",):
                continue
            current: Any = getattr(self, key)
            if current is not None:
                out[key] = str(current)
        return out


def _grep_first(root: Path, glob_specs: list[str], pattern: str) -> str | None:
    for spec in glob_specs:
        for file in expand_glob_files(root, spec):
            try:
                text = file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                return match.group(0)
    return None


def _kernel_version(boot_dir: Path) -> str:
    """Mirror the 3-step `strings boot/kernel` kernel-version fallback chain."""
    kernel = boot_dir / "kernel"
    if not kernel.is_file():
        return ""

    def printable() -> str:
        data = kernel.read_bytes()
        if data[:2] == b"\x1f\x8b":
            try:
                data = gzip.decompress(data)
            except OSError:
                pass
        chunks = re.findall(rb"[ -~]{8,}", data)
        return "\n".join(c.decode("ascii", errors="ignore") for c in chunks)

    text = printable()
    match = re.search(r"Linux version\s+([\d.]+-[\w-]+)", text)
    if match:
        return match.group(1)
    match = re.search(r"\b\d+\.\d+\.\d+-[\w.-]+", text)
    if match:
        return match.group(0)[:-1] or match.group(0)
    match = re.search(r"\b\d+\.\d+\.\d+-[\w.-]+", text)
    if match:
        return match.group(0)
    return ""


def derive(root: Path, store: PropStore) -> FirmwareInfo:
    """Run the full cascade against an extracted firmware tree."""
    info = FirmwareInfo()
    g = store.get

    info.flavor = _clean(
        g("ro.build.flavor", _SYS_LOCS)
        or g("ro.vendor.build.flavor", _VENDOR_LOCS)
        or g("ro.system.build.flavor", _SYS_ONLY_LOCS)
        or g("ro.build.type", _SYS_LOCS)
    )
    info.release = _clean(
        g("ro.build.version.release", _SYS_LOCS)
        or g("ro.vendor.build.version.release", _VENDOR_LOCS)
        or g("ro.system.build.version.release", _SYS_ONLY_LOCS)
    )
    info.id = _clean(
        g("ro.build.id", _SYS_LOCS)
        or g("ro.vendor.build.id", _VENDOR_LOCS)
        or g("ro.system.build.id", _SYS_ONLY_LOCS)
    )
    info.tags = _clean(
        g("ro.build.tags", _SYS_LOCS)
        or g("ro.vendor.build.tags", _VENDOR_LOCS)
        or g("ro.system.build.tags", _SYS_ONLY_LOCS)
    )
    info.platform = _clean(
        g("ro.board.platform", _SYS_LOCS)
        or g("ro.vendor.board.platform", _VENDOR_LOCS)
        or g("ro.system.board.platform", _SYS_ONLY_LOCS)
    )
    info.manufacturer = _clean(
        g("ro.product.manufacturer", _SYS_LOCS)
        or g("ro.product.brand.sub", ["system/system/euclid/my_product"])
        or g("ro.vendor.product.manufacturer", _VENDOR_LOCS)
        or g("ro.product.vendor.manufacturer", _VENDOR_LOCS)
        or g("ro.system.product.manufacturer", _SYS_ONLY_LOCS)
        or g("ro.product.system.manufacturer", _SYS_ONLY_LOCS)
        or g("ro.product.odm.manufacturer", ["vendor/odm"])
        or g("ro.product.manufacturer", ["{oppo_product,my_product,product}"])
        or g("ro.product.manufacturer", ["vendor/euclid/*"])
        or g("ro.system.product.manufacturer", ["vendor/euclid/*"])
        or g("ro.product.product.manufacturer", ["vendor/euclid/product"])
        or g("ro.product.vendor.manufacturer", _VENDOR_LOCS)
        or g("ro.product.system.manufacturer", _SYS_ONLY_LOCS)
    )
    info.fingerprint = _clean(
        g("ro.build.fingerprint", _SYS_ONLY_LOCS)
        or g("ro.vendor.build.fingerprint", _VENDOR_LOCS)
        or g("ro.system.build.fingerprint", _SYS_ONLY_LOCS)
        or g("ro.product.build.fingerprint", _PRODUCT_LOCS)
        or g("ro.build.fingerprint", ["{oppo_product,my_product}"])
        or g("ro.system.build.fingerprint", ["my_product"])
        or g("ro.vendor.build.fingerprint", ["my_product"])
        or g("ro.bootimage.build.fingerprint", _VENDOR_LOCS)
    )
    info.brand = _clean(
        g("ro.product.brand", _SYS_LOCS)
        or g("ro.product.brand.sub", ["system/system/euclid/my_product"])
        or g("ro.product.vendor.brand", _VENDOR_LOCS)
        or g("ro.vendor.product.brand", _VENDOR_LOCS)
        or g("ro.product.system.brand", _SYS_ONLY_LOCS)
    )
    # OPPO brand override: prefer euclid value if empty or "OPPO"
    if not info.brand or info.brand == "OPPO":
        info.brand = _clean(g("ro.product.system.brand", ["vendor/euclid/*"]))
    if not info.brand:
        info.brand = _clean(
            g("ro.product.product.brand", ["vendor/euclid/product"])
            or g("ro.product.odm.brand", ["vendor/odm"])
            or g("ro.product.brand", ["{oppo_product,my_product}"])
            or g("ro.product.brand", ["vendor/euclid/*"])
        )
    if not info.brand and info.fingerprint:
        info.brand = info.fingerprint.split("/", 1)[0]

    info.codename = _clean(
        g("ro.product.device", ["{vendor,system,system/system}"])
        or g("ro.vendor.product.device.oem", ["vendor/euclid/odm"])
        or g("ro.product.vendor.device", _VENDOR_LOCS)
        or g("ro.vendor.product.device", _VENDOR_LOCS)
        or g("ro.product.system.device", _SYS_ONLY_LOCS)
        or g("ro.product.system.device", ["vendor/euclid/*"])
        or g("ro.product.product.device", ["vendor/euclid/*"])
        or g("ro.product.product.model", ["vendor/euclid/*"])
        or g("ro.product.device", ["{oppo_product,my_product}"])
        or g("ro.product.product.device", ["oppo_product"])
        or g("ro.product.system.device", ["my_product"])
        or g("ro.product.vendor.device", ["my_product"])
    )
    if not info.codename and info.fingerprint:
        try:
            info.codename = info.fingerprint.split("/", 2)[2].split(":", 1)[0]
        except IndexError:
            pass
    if not info.codename:
        info.codename = _grep_first(root, ["{system,system/system}/build*.prop"], r"(?<=^ro.build.fota.version=)[^\r\n]*")
        if info.codename:
            info.codename = info.codename.split("-", 1)[0]
    if not info.codename:
        info.codename = _clean(g("ro.build.product", ["{vendor,system,system/system}"]))

    info.description = _clean(
        g("ro.build.description", _SYS_LOCS)
        or g("ro.vendor.build.description", _VENDOR_LOCS)
        or g("ro.system.build.description", _SYS_ONLY_LOCS)
        or g("ro.product.build.description", _PRODUCT_LOCS)
    )
    info.incremental = _clean(
        g("ro.build.version.incremental", _SYS_LOCS)
        or g("ro.vendor.build.version.incremental", _VENDOR_LOCS)
        or g("ro.system.build.version.incremental", _SYS_ONLY_LOCS)
        or g("ro.build.version.incremental", ["my_product"])
        or g("ro.system.build.version.incremental", ["my_product"])
        or g("ro.vendor.build.version.incremental", ["my_product"])
    )
    # Realme incremental fallbacks
    if not info.incremental and "realme" in info.brand.lower():
        matches = grep_value(
            root, r"(?<=^ro.build.version.ota=)[^\r\n]*", ["vendor/euclid/product/build.prop", "oppo_product/build.prop"]
        )
        if matches:
            ota = matches[0]
            info.incremental = "_".join(ota.split("_")[-2:])
    if not info.incremental and info.description:
        info.incremental = " ".join(info.description.split()).split(" ")[3] if len(info.description.split()) >= 4 else ""
    if not info.description and info.incremental:
        info.description = f"{info.flavor} {info.release} {info.id} {info.incremental} {info.tags}".strip()
    if not info.description and not info.incremental:
        info.description = info.codename

    info.abilist = _clean(
        g("ro.product.cpu.abilist", _SYS_ONLY_LOCS) or g("ro.vendor.product.cpu.abilist", _VENDOR_LOCS)
    )
    info.locale = _clean(g("ro.product.locale", _SYS_ONLY_LOCS)) or "undefined"
    info.density = _clean(g("ro.sf.lcd_density", _SYS_ONLY_LOCS)) or "undefined"
    info.is_ab = _clean(g("ro.build.ab_update", _SYS_LOCS)) or "false"
    info.treble_support = _clean(g("ro.treble.enabled", _SYS_ONLY_LOCS)) or "false"

    info.otaver = _clean(
        g("ro.build.version.ota", ["{vendor/euclid/product,oppo_product,system,system/system}"])
    )
    if info.otaver and not info.fingerprint:
        info.branch = info.otaver.replace(" ", "-")
    if not info.otaver:
        info.otaver = _clean(g("ro.build.fota.version", _SYS_ONLY_LOCS))
    if not info.branch:
        info.branch = info.description.replace(" ", "-") if info.description else ""

    # Vendor-specific overrides (prop_override + grep fallbacks)
    overridden_platform = _clean(
        g("ro.vendor.mediatek.platform", _VENDOR_LOCS) or g("ro.board.platform", _VENDOR_LOCS)
    )
    if overridden_platform:
        info.platform = overridden_platform

    new_mfr = grep_value(root, r"(?<=^ro.product.odm.brand=)[^\r\n]*",
        ["odm/etc/*/build.default.prop", "vendor/odm/etc/build.prop", "odm/etc/build.prop", "my_manifest/build.prop"])
    if new_mfr:
        info.manufacturer = new_mfr[-1]
    new_codename = grep_value(root, r"(?<=^ro.product.odm.model=)[^\r\n]*", ["my_manifest/build.prop"])
    if new_codename:
        info.codename = new_codename[-1]
    if not info.codename:
        alt = grep_value(root, r"(?<=^ro.product.odm.device=)[^\r\n]*",
            ["odm/etc/*/build.default.prop", "vendor/odm/etc/build.prop", "odm/etc/build.prop", "my_manifest/build.prop"])
        if alt:
            info.codename = alt[-1]

    for key, locs in (
        ("ro.build.fingerprint", ["my_manifest", "tr_manifest"]),
        ("ro.tr_product.build.fingerprint", ["tr_product"]),
        ("ro.product.build.fingerprint", ["product"]),
    ):
        val = _clean(g(key, locs))
        if val:
            info.fingerprint = val
    if not info.fingerprint:
        val = _clean(g("ro.tr_region.build.fingerprint", ["tr_region"]))
        if val:
            info.fingerprint = val

    brand_ext = _clean(g("ro.product.system_ext.brand", ["system_ext"]))
    if brand_ext:
        info.brand = brand_ext
    density_v = g("ro.sf.lcd_density", ["{vendor,system,system/system,odm}"])
    if density_v:
        info.density = _clean(density_v)

    info.transname = _clean(g("ro.product.product.tran.device.name.default", ["product"]))
    info.osver = _clean(g("ro.os.version.release", ["product"]))
    xosver = g("ro.tranos.version", ["product"]) or g("ro.tranos.version", ["tr_product"])
    info.xosver = _clean(xosver)
    info.sec_patch = _clean(g("ro.build.version.security_patch", _SYS_ONLY_LOCS))
    xosid = (
        g("ro.build.display.id", _TR_LOCS)
        or g("ro.build.display.id", ["tr_region"])
        or g("ro.build.display.id", ["tr_product"])
        or g("ro.build.display.id", ["product"])
    )
    info.xosid = _clean(xosid)
    if info.xosid:
        info.branch = info.xosid.replace(" ", "-")

    info.tranchipset = _overlay_chipset(root, ("TranSettingsApkResOverlay", "ItelSettingsResOverlay"))
    if not info.tranchipset:
        raw_cpu = _clean(_file_text(root / "tr_product/etc/asset/transettings/cpu_info"))
        if raw_cpu and raw_cpu.lower() not in ("unknown", "null", "undefined"):
            info.tranchipset = raw_cpu

    cpu_model = _grep_first(root, ["my_product/etc/build.prop"], r"(?<=^ro.product.oplus.cpuinfo=)[^\r\n]*")
    if cpu_model:
        xml_text = _file_text(root / "my_stock/etc/extension/config_processor_com.android.settings.xml")
        match = re.search(rf'model_name="{re.escape(cpu_model)}"[^>]*name_en="([^"]*)"', xml_text)
        if match:
            info.opchipset = match.group(1)

    opnames = grep_value(root, r"(?<=^ro.vendor.oplus.market.name=)[^\r\n]*", ["my_manifest/build.prop"])
    if opnames:
        info.opname = opnames[0]

    xiaomi_vals = grep_value(
        root,
        r"(?<=^ro\.product\.odm\.marketname=)[^\r\n]*",
        ["odm/etc/*", "vendor/odm/etc/*"],
    )
    kept = sorted({v.strip() for v in xiaomi_vals if re.fullmatch(r"[a-z]*", v) is None})
    if kept:
        info.xiaominame = " | ".join(kept)

    moto_vals: list[str] = []
    for spec in ("*/etc/build.prop", "system/system/build.prop", "product/etc/motorola/props/*.prop"):
        for file in expand_glob_files(root, spec):
            try:
                text = file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                if re.match(r"^ro\.product\..*\.model=", line.strip()):
                    value = _STRIP_RE.sub(" ", line.strip().split("=", 1)[1].rstrip("\r")).strip()
                    if "moto" in value.lower():
                        moto_vals.append(value)
    kept_moto = sorted(set(moto_vals))
    if kept_moto:
        info.motoname = " | ".join(kept_moto)

    if not info.transname:
        json_hits = _grep_json(root / "odm/etc/goldwatermark/configs/TranssionWM.json")
        if json_hits:
            info.transname = json_hits[0]
    if not info.transname:
        json_hits = _grep_json(root / "odm/etc/asset/camera/goldwatermark/configs/TranssionWM.json")
        if json_hits and info.manufacturer:
            info.transname = f"{info.manufacturer} {json_hits[0]}"

    info.repo = f"{info.manufacturer}/{info.codename}" if info.codename else info.manufacturer

    info.kernel_version = _kernel_version(root / "boot")
    info.date = _clean(
        _grep_first(root, ["tr_manifest/build.prop"], r"(?<=^ro.build.date=)[^\r\n]*")
        or g("ro.build.date", ["{system,system/system,tr_product,vendor}"])
        or g("ro.build.date.utc", ["{system,system/system,tr_product,vendor}"])
    )

    return info


def _overlay_chipset(root: Path, overlay_names: tuple[str, ...]) -> str:
    """Transsion TranSettings overlay: value of cpu_rate_cores in strings.xml."""
    for name in overlay_names:
        apk = root / "product" / "overlay" / name / f"{name}.apk"
        if not apk.is_file():
            continue
        try:
            apktool = _apktool_path()
            if apktool is None:
                return ""
            from dumprx.process import run

            out_dir = root / "decoded_overlay"
            run([apktool, "d", str(apk), "-o", str(out_dir), "-f"], check=False)
            strings_xml = out_dir / "res" / "values" / "strings.xml"
            if strings_xml.is_file():
                match = re.search(
                    r'<string name="cpu_rate_cores">(.*?)</string>',
                    strings_xml.read_text(encoding="utf-8", errors="replace"),
                )
                if match:
                    val = match.group(1).strip()
                    if val and val.lower() not in ("unknown", "null", "undefined"):
                        return val
        except Exception:  # noqa: BLE001 - overlay decode is best-effort
            logger.debug("overlay chipset decode failed for {}", name)
    return ""


def _apktool_path() -> str | None:
    from dumprx.process import which

    return which("apktool")


_STRIP_RE = re.compile(r"[ \t\r\n]+")


def _grep_json(path: Path) -> list[str]:
    """Values of TEXT_BRAND_NAME in a TranssionWM.json (port of grep -oP)."""
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    matches = re.findall(r'TEXT_BRAND_NAME": "([^"]*)"', text)
    return matches


def _file_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


__all__ = ["FirmwareInfo", "derive"]
