"""board-info.txt: version-baseband / version-trustzone / version-vendor.

Port of the `find | strings | grep | sed` chain in dumper.sh. Files under
modem/ and tz*/ are scanned for printable version strings; vendor/build.prop
contributes the A/B vendor build date.
"""

from __future__ import annotations

import re
from pathlib import Path

_BASEBAND_RE = re.compile(r"QC_IMAGE_VERSION_STRING=MPSS\.([0-9A-Za-z._-]+)")
_TRUSTZONE_RE = re.compile(r"QC_IMAGE_VERSION_STRING=(MPSS\.)?[0-9A-Za-z._-]+")
_VENDOR_DATE_RE = re.compile(r"ro\.vendor\.build\.date\.utc=(\d+)")


def _printable(lines: list[str]) -> str:
    return "\n".join(re.findall(r"[ -~]{6,}", "\n".join(lines)))


def board_info_lines(root: Path) -> list[str]:
    """Return the sorted-unique board-info.txt lines, empty list if none."""
    lines: list[str] = []

    baseband = _scan_files(root, "modem", _BASEBAND_RE)
    for match in baseband:
        # bash: strip MPSS. prefix, cut -c 4- (skip 3 chars), prefix requirement
        value = match.group(1)
        if len(value) > 3:
            lines.append(f"require version-baseband={value[3:]}")

    trustzones = _scan_files(root, "tz*", _TRUSTZONE_RE)
    for match in trustzones:
        raw = match.group(0)
        lines.append(re.sub(r"^QC_IMAGE_VERSION_STRING", "require version-trustzone", raw))

    vendor_prop = root / "vendor" / "build.prop"
    if vendor_prop.is_file():
        try:
            text = vendor_prop.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        for match in _VENDOR_DATE_RE.finditer(text):
            lines.append(f"require version-vendor={match.group(1)}")

    return sorted(set(lines))


def _scan_files(root: Path, pattern: str, regex: re.Pattern[str]) -> list[re.Match[str]]:
    matches: list[re.Match[str]] = []
    for sub in sorted(root.glob(pattern)):
        if not sub.is_dir():
            continue
        for file in sorted(p for p in sub.rglob("*") if p.is_file()):
            try:
                data = file.read_bytes()
            except OSError:
                continue
            text = data.decode("latin-1", errors="ignore")
            matches.extend(regex.finditer(text))
    return matches


__all__ = ["board_info_lines"]
