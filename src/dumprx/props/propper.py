"""Single-pass build.prop parsing + first-match cascade lookup.

Replaces the `find | xargs grep` subprocess chains in dumper.sh `prop_get`.
Every build.prop file under the firmware tree is parsed at most once and its
key/value pairs cached, so the whole property phase touches each file once.
"""

from __future__ import annotations

import re
from pathlib import Path


def parse_prop_file(path: Path) -> dict[str, str]:
    """Parse a build.prop text file into a key -> value dict (single pass)."""
    result: dict[str, str] = {}
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                value = value.strip()
                if value.endswith("\\"):
                    value = value[:-1].strip()
                if key.strip():
                    result.setdefault(key.strip(), value)
        return result
    except OSError:
        return {}


def build_prop_files(root: Path, dirs: list[Path]) -> list[Path]:
    """build*.prop files directly in each dir or one subdir deep (maxdepth 2)."""
    files: list[Path] = []
    for directory in dirs:
        if not directory.is_dir():
            continue
        files.extend(sorted(directory.glob("build*.prop")))
        for subdir in sorted(p for p in directory.iterdir() if p.is_dir()):
            files.extend(sorted(subdir.glob("build*.prop")))
    return sorted(set(files))


def expand_locs(spec: str) -> list[Path]:
    """Parse a dir spec: `{a,b}` groups and trailing `/*` globs (relative)."""
    base = Path(".")
    spec = spec.strip()
    if spec.startswith("{") and "}" in spec:
        inner, _, rest = spec[1:].partition("}")
        dirs = [Path(part.strip()) for part in inner.split(",") if part.strip()]
    else:
        dirs = [Path(spec)]
    expanded: list[Path] = []
    for d in dirs:
        text = str(d)
        if text.endswith("/*"):
            parent = base / text[:-2]
            if parent.is_dir():
                expanded.extend(
                    p for p in sorted(parent.iterdir()) if p.is_dir()
                )
        else:
            expanded.append(base / d)
    return expanded


class PropStore:
    """Cached reader for all build*.prop files under a firmware OUTDIR."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._parsed: dict[Path, dict[str, str]] = {}

    def _props_for(self, spec: str) -> list[dict[str, str]]:
        located = [self.root / d for d in expand_locs(spec)]
        props: list[dict[str, str]] = []
        for file in build_prop_files(self.root, located):
            if file not in self._parsed:
                self._parsed[file] = parse_prop_file(file)
            props.append(self._parsed[file])
        return props

    def get(self, key: str, locs: list[str]) -> str | None:
        """First non-empty value for key across locs, in cascade order."""
        for loc in locs:
            for props in self._props_for(loc):
                value = props.get(key)
                if value is not None and value != "":
                    return value
        return None

    def files(self) -> list[Path]:
        """Every parsed build.prop (for existence gates / iteration)."""
        return sorted(self._parsed)


_STRIP_ATTR = re.compile(r"[ \t\r\n]+")


def grep_value(root: Path, pattern: str, file_globs: list[str]) -> list[str]:
    """Port of `grep -hoP '(?<=^K=).*' <glob...>`: all matches across files.

    Returns values with attributes collapsed (like `grep -oP` on a single
    line would, and mirroring `awk '{$1=$1};1'` used in model-name joins).
    """
    regex = re.compile(pattern, re.MULTILINE)
    matches: list[str] = []
    for glob_spec in file_globs:
        for file in expand_glob_files(root, glob_spec):
            try:
                text = file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for match in regex.finditer(text):
                value = match.group(0) if match.lastindex else match.group(0)
                value = _STRIP_ATTR.sub(" ", value).strip()
                if value:
                    matches.append(value)
    return matches


def _brace_variants(spec: str) -> list[str]:
    """Expand a leading `{a,b}` group into plain paths; else [spec]."""
    if spec.startswith("{") and "}" in spec:
        inner, _, rest = spec[1:].partition("}")
        parts = [part.strip() for part in inner.split(",") if part.strip()]
        return [f"{part}{rest}" for part in parts] if parts else [spec]
    return [spec]


def expand_glob_files(root: Path, glob_spec: str) -> list[Path]:
    """Expand a file glob spec like `odm/etc/*/build.default.prop` under root."""
    found: list[Path] = []
    for variant in _brace_variants(glob_spec):
        direct = root / variant
        if direct.is_file():
            found.append(direct)
        else:
            found.extend(root.glob(variant))
    return sorted(set(found))


__all__ = [
    "PropStore",
    "build_prop_files",
    "expand_glob_files",
    "expand_locs",
    "grep_value",
    "parse_prop_file",
]
