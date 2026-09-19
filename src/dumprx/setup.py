"""First-run device setup: system packages, uv, runtime clones, uv sync, state.

Pythonized replacement for the legacy `setup.sh`. `run_setup()` installs
prerequisites and records completion in a machine-scoped XDG state file so the
CLI can auto-run setup on first use.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from dumprx.tools import ensure_runtime_clones

UV_INSTALL_URL = "https://astral.sh/uv/install.sh"

# Package lists mirrored verbatim from setup.sh (one string per manager).
_PACKAGES = {
    "apt": (
        "unace unrar zip unzip p7zip-full p7zip-rar sharutils rar uudeview mpack arj "
        "cabextract device-tree-compiler liblzma-dev python3-pip brotli liblz4-tool axel "
        "gawk aria2 detox cpio rename liblz4-dev jq git-lfs rsync neofetch file apktool "
        "libarchive-tools"
    ).split(),
    "dnf": (
        "unace unrar zip unzip sharutils uudeview arj cabextract file-roller dtc "
        "python3-pip brotli axel aria2 detox cpio lz4 python3-devel xz-devel p7zip "
        "p7zip-plugins git-lfs"
    ).split(),
    "pacman": (
        "unace unrar p7zip sharutils uudeview arj cabextract file-roller dtc brotli "
        "axel gawk aria2 detox cpio lz4 jq git-lfs"
    ).split(),
    "apk": (
        "zip unzip p7zip uudeview arj cabextract dtc brotli lz4 axel gawk aria2 cpio "
        "jq git-lfs rsync neofetch file libarchive-tools bash curl python3 py3-pip"
    ).split(),
    "brew": (
        "protobuf xz brotli lz4 aria2 detox coreutils p7zip gawk git-lfs"
    ).split(),
}


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("dumprx")
    except Exception:  # noqa: BLE001 - metadata read failure is non-fatal
        return "unknown"


def state_path() -> Path:
    """Machine-scoped state file under the XDG state dir."""
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "dumprx" / "state.json"


def setup_complete() -> bool:
    """True only when a full success marker exists in the state file."""
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return data.get("complete") is True


def mark_complete(pm: str | None = None) -> None:
    """Write the success marker. Failures are logged, never raise."""
    path = state_path()
    data = {
        "complete": True,
        "os": platform.system().lower(),
        "pm": pm,
        "version": _version(),
        "at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("could not write setup state file {}: {}", path, exc)


def detect_package_manager() -> str | None:
    """First available of apt/dnf/pacman/apk/brew, mirroring setup.sh order."""
    for manager in ("apt", "dnf", "pacman", "apk", "brew"):
        if shutil.which(manager):
            return manager
    return None


def _sudo_prefix() -> list[str]:
    try:
        if os.geteuid() == 0:
            return []
    except AttributeError:
        pass
    return ["sudo"] if shutil.which("sudo") else []


def run_visible(argv: Sequence[str], *, cwd: Path | None = None) -> int:
    """Run a command with inherited stdio so prompts and progress stay visible.

    Raises RuntimeError on non-zero exit (setup.sh `abort` parity).
    """
    proc = subprocess.run(list(argv), cwd=cwd, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(map(str, argv))}")
    return proc.returncode


def install_system_packages(pm: str) -> None:
    """Install the fixed per-manager package list, escalating via sudo when needed."""
    sudo = _sudo_prefix()
    packages = _PACKAGES[pm]
    if pm == "apt":
        run_visible([*sudo, "apt", "-y", "update"])
        run_visible([*sudo, "apt", "install", "-y", *packages])
    elif pm == "dnf":
        run_visible([*sudo, "dnf", "install", "-y", *packages])
    elif pm == "pacman":
        run_visible([*sudo, "pacman", "-Sy", "--needed", "--noconfirm", *packages])
    elif pm == "apk":
        run_visible([*sudo, "apk", "add", "--no-cache", *packages])
    elif pm == "brew":
        run_visible(["brew", "install", *packages])


def install_uv() -> None:
    """Install uv via the astral installer, honoring SUDO_USER like setup.sh."""
    script = f"$(curl -sL {UV_INSTALL_URL})"
    argv: list[str] = ["bash", "-c", script]
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and shutil.which("sudo"):
        argv = ["sudo", "-u", sudo_user, *argv]
    run_visible(argv)


def run_setup(config, *, explicit: bool = False) -> int:
    """Install system packages, uv, runtime clones, and python deps; record state.

    explicit=True propagates failure as 1; auto-run warns and returns 0 so the
    dump path can continue (spec: auto-setup failure tolerance).
    """
    try:
        pm = detect_package_manager()
        if pm is None:
            logger.warning("no supported package manager found; skipping system packages")
        else:
            logger.info("detected package manager: {}", pm)
            install_system_packages(pm)

        logger.info("installing uv")
        install_uv()

        logger.info("syncing runtime helper tools")
        ensure_runtime_clones(config.paths.utilsdir)

        logger.info("syncing python dependencies")
        run_visible(["uv", "sync"], cwd=config.paths.project_dir)

        mark_complete(pm)
        logger.info("setup complete")
        return 0
    except Exception as exc:  # noqa: BLE001 - setup failure is surfaced, not swallowed
        if explicit:
            logger.error("setup failed: {}", exc)
            return 1
        logger.warning("auto setup failed (continuing): {}", exc)
        return 0


__all__ = [
    "UV_INSTALL_URL",
    "detect_package_manager",
    "install_system_packages",
    "install_uv",
    "mark_complete",
    "run_setup",
    "run_visible",
    "setup_complete",
    "state_path",
]
