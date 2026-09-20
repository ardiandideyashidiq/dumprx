"""README dump card and Telegram HTML builder from FirmwareInfo.

Ports dumper.sh's append sequence (lines 1339-1401) line-for-line so the
generated card stays byte-compatible with the Bash one.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from dumprx.props.models import FirmwareInfo


def _line(label: str, value: str) -> list[str]:
    return [f"- {label}: {value}"] if value else []


def render_readme(info: FirmwareInfo) -> list[str]:
    """Build the README body lines in bash append order."""
    lines = ["## FIRMWARE DUMP", f"### {info.description}\n"]
    lines += _line("Transsion name", info.transname)
    lines += _line("Xiaomi name", info.xiaominame)
    lines += _line("Moto name", info.motoname)
    lines += _line("OP name", info.opname)
    lines += _line("TranOS build", info.xosid)
    lines += _line("TranOS version", info.xosver)
    lines += _line("Brand", info.manufacturer)
    lines += _line("Model", info.codename)

    if info.platform:
        tranchipset = info.tranchipset if info.tranchipset and info.tranchipset.lower() != "unknown" else ""
        opchipset = info.opchipset if info.opchipset and info.opchipset.lower() != "unknown" else ""
        if tranchipset:
            lines.append(f"- Platform: {info.platform} ({tranchipset})")
        elif opchipset:
            lines.append(f"- Platform: {info.platform} ({opchipset})")
        else:
            lines.append(f"- Platform: {info.platform}")

    lines += _line("Android build", info.id)
    lines += _line("Android version", info.release)
    lines += _line("Kernel version", info.kernel_version)
    lines += _line("Security patch", info.sec_patch)
    lines += _line("CPU abilist", info.abilist)
    lines += _line("A/B device", info.is_ab)
    lines += _line("Treble device", info.treble_support)
    lines += _line("Screen density", info.density)
    lines += _line("Fingerprint", info.fingerprint)
    lines += _line("Build date", info.date)
    return lines


def write_readme(outdir: Path, info: FirmwareInfo) -> Path:
    target = outdir / "README.md"
    target.write_text("\n".join(render_readme(info)) + "\n", encoding="utf-8")
    logger.info("README.md generated ({})", target)
    return target


def build_tg_html(info: FirmwareInfo, repo_url: str = "", repo_label: str = "") -> str:
    """Telegram blockquote HTML, mirroring the bash printf sequence."""
    parts: list[str] = []
    for label, value in (
        ("Transsion name", info.transname),
        ("Xiaomi name", info.xiaominame),
        ("Moto name", info.motoname),
        ("OP name", info.opname),
        ("TranOS build", info.xosid),
        ("TranOS ver", info.xosver),
    ):
        if value:
            parts.append(f"\n<b>{label}: %s</b>" % f"<code>{value}</code>")
    parts.append("\n<b>Brand: %s</b>" % f"<code>{info.manufacturer}</code>")
    parts.append("\n<b>Model: %s</b>" % f"<code>{info.codename}</code>")
    ts_chipset = (
        f" ({info.tranchipset})"
        if info.tranchipset and info.tranchipset.lower() != "unknown"
        else ""
    )
    parts.append("\n<b>Platform: %s</b>" % f"<code>{info.platform}{ts_chipset}</code>")
    parts.append("\n<b>Android build: %s</b>" % f"<code>{info.id}</code>")
    parts.append("\n<b>Android ver: %s</b>" % f"<code>{info.release}</code>")
    if info.kernel_version:
        parts.append("\n<b>Kernel ver: %s</b>" % f"<code>{info.kernel_version}</code>")
    parts.append("\n<b>Security patch: %s</b>" % f"<code>{info.sec_patch}</code>")
    parts.append("\n<b>Fingerprint: %s</b>" % f"<code>{info.fingerprint}</code>")
    if repo_url:
        parts.append(f"\n<a href=\"{repo_url}\">{repo_label or 'Repository Tree'}</a>")
    return "<blockquote><b>FIRMWARE DUMP INFO</b></blockquote>" + "".join(parts)


__all__ = ["build_tg_html", "render_readme", "write_readme"]
