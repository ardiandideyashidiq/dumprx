"""Input content-hash ledger: skip re-dumping an exact firmware file.

Approach A redundancy. A streaming sha256 of the input file keys a
machine-scoped ledger (XDG state dir, same pattern as `setup.state_path`). A
ledger hit bails before any extraction; entries are written only after a dump
has fully succeeded (local commit, or publish in gitlab/github mode), so a
failed or un-pushed run is never recorded.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

_CHUNK = 1 << 20
_LEDGER_FILE = "dumps.json"


def _ledger_path() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "dumprx" / _LEDGER_FILE


def sha256_stream(path: Path) -> str:
    """Streaming sha256 of a file; empty string on read failure."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(_CHUNK), b""):
                digest.update(chunk)
    except OSError as exc:
        logger.warning("cannot hash {}: {}", path, exc)
        return ""
    return digest.hexdigest()


def lookup(digest: str) -> dict | None:
    """Stored dump info for `digest`, or None when absent or stale.

    An entry is stale when its recorded outdir no longer holds all_files.txt
    (the user deleted the local dump), so a re-dump is allowed again.
    """
    if not digest:
        return None
    try:
        ledger = json.loads(_ledger_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entry = ledger.get(digest)
    if entry is None:
        return None
    if not (Path(entry.get("outdir", "")) / "all_files.txt").is_file():
        return None
    return entry


def record(digest: str, *, outdir: Path, mode: str, info) -> None:
    """Store a completed dump keyed by input digest. Never raises."""
    if not digest:
        return
    try:
        ledger = json.loads(_ledger_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ledger = {}
    ledger[digest] = {
        "outdir": str(outdir),
        "mode": mode,
        "identity": {
            "manufacturer": getattr(info, "manufacturer", ""),
            "codename": getattr(info, "codename", ""),
            "branch": getattr(info, "branch", ""),
        },
        "at": datetime.now(timezone.utc).isoformat(),
    }
    path = _ledger_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("could not write dump ledger {}: {}", path, exc)


__all__ = ["lookup", "record", "sha256_stream"]
