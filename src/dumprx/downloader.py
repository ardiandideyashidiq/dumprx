"""URL downloader dispatch, mirroring dumper.sh's hoster branches.

Returns the tool + argv for a URL; the caller runs it inside INPUTDIR after
clearing it. Local files/folders never go through here (space-path safety is
handled by using Path objects everywhere instead of bash word-splitting).
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from dumprx.process import run


class DownloadError(RuntimeError):
    pass


def select_downloader(url: str, tools) -> tuple[str, list[str]] | None:
    """Pick (tool, argv) for `url`, or None when it is not a remote URL."""
    if not (url.startswith("https://") or url.startswith("http://") or url.startswith("ftp://")):
        return None
    if any(h in url for h in ("mega.nz", "mediafire.com", "drive.google.com")):
        script = tools["mega-media-drive_dl"]
        if script is None:
            raise DownloadError("mega-media-drive_dl.sh missing from utils/downloaders")
        return "script", [str(script), url]
    if "androidfilehost.com" in url:
        script = tools["afh_dl"]
        if script is None:
            raise DownloadError("afh_dl.py missing from utils/downloaders")
        return "script", ["python3", str(script), "-l", url]
    if "/we.tl/" in url:
        transfer = tools["transfer"]
        if transfer is None:
            raise DownloadError("bin/transfer missing from utils")
        return "script", [str(transfer), url]
    # aria2c first, wget fallback (matched on failure by the caller retrying)
    fixed = url.replace("1drv.ms", "1drv.ws")
    return "onearray", [fixed]


def download_into(url: str, inputdir: Path, tools) -> None:
    """Download `url` into a pre-cleared INPUTDIR; may re-try via wget."""
    selected = select_downloader(url, tools)
    if selected is None:
        raise DownloadError(f"not a remote URL: {url}")
    kind, argv = selected
    inputdir.mkdir(parents=True, exist_ok=True)
    for p in inputdir.iterdir():
        if p.is_dir():
            import shutil

            shutil.rmtree(p)
        else:
            p.unlink()
    if kind == "script":
        if not run(argv, cwd=inputdir).ok:
            raise DownloadError(f"downloader failed: {argv[0]}")
        return
    # aria2c first, then wget
    if run(
        [
            "aria2c",
            "-x16",
            "-s8",
            "--console-log-level=warn",
            "--summary-interval=0",
            "--check-certificate=false",
            argv[0],
        ],
        cwd=inputdir,
        timeout=3600 * 8,
    ).ok:
        return
    if not run(
        [
            "wget",
            "-q",
            "--show-progress",
            "--progress=bar:force",
            "--no-check-certificate",
            argv[0],
        ],
        cwd=inputdir,
        timeout=3600 * 8,
    ).ok:
        raise DownloadError(f"download failed: {url}")
    logger.info("downloaded {} into {}", url, inputdir)


__all__ = ["DownloadError", "download_into", "select_downloader"]
