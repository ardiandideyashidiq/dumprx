"""Tool discovery, runtime clone, and external helper resolution."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger

from dumprx.process import run

# GitHub repos cloned at runtime into utils/ (dir name = repo basename)
RUNTIME_CLONES = (
    "bkerler/oppo_ozip_decrypt",
    "bkerler/oppo_decrypt",
    "marin-m/vmlinux-to-elf",
    "ShivamKumarJha/android_tools",
    "HemanthJabalpuri/pacextractor",
)

# name -> path segment inside utils/ (script extensions kept where meaningful)
TOOL_MAP = {
    "simg2img": "bin/simg2img",
    "packsparseimg": "bin/packsparseimg",
    "unsin": "unsin",
    "payload-dumper-go": "bin/payload-dumper-go",
    "dtc": "dtc",
    "vmlinux-to-elf": "vmlinux-to-elf/vmlinux-to-elf",
    "kallsyms-finder": "vmlinux-to-elf/kallsyms-finder",
    "ozipdecrypt": "oppo_ozip_decrypt/ozipdecrypt.py",
    "ofp_qc_decrypt": "oppo_decrypt/ofp_qc_decrypt.py",
    "ofp_mtk_decrypt": "oppo_decrypt/ofp_mtk_decrypt.py",
    "opscrypto": "oppo_decrypt/opscrypto.py",
    "lpunpack": "lpunpack",
    "splituapp": "splituapp.py",
    "pacExtractor": "pacextractor/python/pacExtractor.py",
    "nb0-extract": "nb0-extract",
    "unkdz": "kdztools/unkdz.py",
    "undz": "kdztools/undz.py",
    "ruu_decrypt": "RUU_Decrypt_Tool",
    "extract-ikconfig": "extract-ikconfig",
    "unpackboot": "unpackboot.sh",
    "aml_extract": "aml-upgrade-package-extract",
    "afptool": "bin/afptool",
    "rkImageMaker": "bin/rkImageMaker",
    "transfer": "bin/transfer",
    "avbtool": "avbtool.py",
    "sdat2img": "sdat2img.py",
    "fsck.erofs": "bin/fsck.erofs",
    "mega-media-drive_dl": "downloaders/mega-media-drive_dl.sh",
    "afh_dl": "downloaders/afh_dl.py",
}


@dataclass(frozen=True)
class Tools:
    """Resolved external tool paths (all absolute Paths or None when absent)."""

    utilsdir: Path

    def resolve(self, name: str) -> Path | None:
        segment = TOOL_MAP.get(name, name)
        path = self.utilsdir / segment
        return path if path.is_file() or path.is_dir() else None

    def __getitem__(self, name: str) -> Path | None:
        return self.resolve(name)

    @property
    def seven_zz(self) -> str:
        """System 7zz first, falling back to the vendored binary."""
        from dumprx.process import which

        sys7zz = which("7zz")
        if sys7zz:
            return sys7zz
        vendored = self.utilsdir / "bin" / "7zz"
        return str(vendored) if vendored.exists() else "7zz"

    def require(self, name: str) -> Path:
        resolved = self.resolve(name)
        if resolved is None:
            raise FileNotFoundError(f"required tool not found in utils/: {name}")
        return resolved


def ensure_runtime_clones(utilsdir: Path) -> None:
    """Clone or update runtime tools in parallel, mirroring dumper.sh `& wait`."""
    utilsdir.mkdir(parents=True, exist_ok=True)

    def sync(slug: str) -> None:
        dest = utilsdir / slug.split("/", 1)[1]
        try:
            if dest.joinpath(".git").exists():
                logger.debug("git pull {}", slug)
                run(["git", "-C", str(dest), "pull", "-q"])
            else:
                logger.debug("git clone {}", slug)
                run(
                    ["git", "clone", "-q", f"https://github.com/{slug}.git", str(dest)]
                )
        except Exception as exc:  # noqa: BLE001 - clone failure must not abort dump
            logger.warning("tool clone failed for {}: {}", slug, exc)

    with ThreadPoolExecutor(max_workers=len(RUNTIME_CLONES)) as pool:
        list(pool.map(sync, RUNTIME_CLONES))


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https", "ftp")


__all__ = ["RUNTIME_CLONES", "TOOL_MAP", "Tools", "ensure_runtime_clones", "is_url"]
