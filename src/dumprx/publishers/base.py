"""Shared git machinery: local staged commits, push retry, LFS object upload.

Ports dumper.sh's `retry_push`, `push_lfs_objects`, and `commit_and_push`
(lines 1452-1547). Commits always run locally via `commit_local`; pushing is a
separate `push_all` step. LFS workers must run the literal command
`git lfs push --object-id origin <oid>` - never `retry_push lfs push ...`
(that would expand to `git push lfs push ...`).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dumprx.process import Result, run

_PARTITION_GROUPS = [
    "system_ext",
    "product",
    "system_dlkm",
    "odm",
    "odm_dlkm",
    "init_boot",
    "vendor_boot",
    "vendor_dlkm",
    "vendor",
    "system",
    "tr_product",
    "tr_region",
]
_MIB = 1024 * 1024
_LFS_SIZES = {"gitlab": 100 * _MIB, "github": 50 * _MIB}


class PushError(RuntimeError):
    pass


def git(*args: str, cwd: Path, capture: bool = False, timeout: float = 3600) -> Result:
    return run(["git", *args], cwd=str(cwd), timeout=timeout, capture=capture)


def retry_push(cwd: Path, *args: str, max_attempts: int = 5) -> bool:
    """`git push "$@"` with up to `max_attempts` attempts, 5s sleeps."""
    for attempt in range(max_attempts):
        result = git("push", *args, cwd=cwd)
        if result.ok:
            return True
        if attempt + 1 < max_attempts:
            print("Retrying push (attempt {} of {})...".format(attempt + 1, max_attempts))
        import time

        time.sleep(5)
    print("Failed to push after {} attempts.".format(max_attempts))
    return False


def _lfs_oids(cwd: Path) -> list[str]:
    result = git("lfs", "ls-files", "--all", "-l", cwd=cwd, capture=True, timeout=120)
    oids: list[str] = []
    for line in result.stdout_text.splitlines():
        oid = line.split()[0] if line.split() else ""
        if oid:
            oids.append(oid)
    return oids


def _push_lfs_oid(cwd: Path, oid: str) -> None:
    for attempt in range(5):
        result = git("lfs", "push", "--object-id", "origin", oid, cwd=cwd, timeout=3600)
        if result.ok:
            return
        import time

        time.sleep(5)
        if attempt + 1 == 5:
            raise PushError(f"Failed to push LFS object {oid} after 5 attempts.")


def push_lfs_objects(cwd: Path, workers: int = 8) -> list[str]:
    """Upload all LFS objects via 8 parallel, independent `lfs push --object-id`."""
    oids = _lfs_oids(cwd)
    if not oids:
        return []
    failed: list[str] = []

    def one(oid: str) -> None:
        print(f"Pushing LFS object: {oid}")
        try:
            _push_lfs_oid(cwd, oid)
        except PushError as exc:
            failed.append(str(exc))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, oids))

    if failed:
        raise PushError("; ".join(failed))
    return oids


def init_repo(outdir: Path, branch: str, fallback_branch: str = "") -> str:
    """git init, local http.postBuffer, branch checkout (+fallback), .gitignore, git user."""
    if git("init", cwd=outdir).ok:
        print("Starting Git Init...")
    git("config", "http.postBuffer", "524288000", cwd=outdir)  # local config only

    branch_name = branch
    if not git("checkout", "-b", branch, cwd=outdir).ok:
        if fallback_branch and git("checkout", "-b", fallback_branch, cwd=outdir).ok:
            branch_name = fallback_branch
    _write_gitignore(outdir)

    if not git("config", "--get", "user.email", capture=True, cwd=outdir).ok:
        git("config", "user.email", "ramanarubp@gmail.com", cwd=outdir)
    if not git("config", "--get", "user.name", capture=True, cwd=outdir).ok:
        git("config", "user.name", "Rama Bondan Prakoso", cwd=outdir)
    return branch_name


def _write_gitignore(outdir: Path) -> None:
    targets = sorted({str(p.relative_to(outdir)) for p in outdir.rglob("*") if p.is_file()})
    ignored = [t for t in targets if "*sensetime*" in t or t.endswith(".lic")]
    if not ignored:
        if (outdir / ".gitignore").is_file():
            (outdir / ".gitignore").unlink()
        return
    (outdir / ".gitignore").write_text("\n".join(ignored) + "\n", encoding="utf-8")


def _commit_if_staged(outdir: Path, message: str, *paths: str) -> bool:
    """`git add` paths and commit only when something was staged; returns whether committed."""
    git("add", *paths, cwd=outdir)
    if git("diff", "--cached", "--quiet", cwd=outdir, capture=True).ok:
        return False
    if not git("commit", "-sm", message, cwd=outdir).ok:
        raise PushError(f"commit failed: {message}")
    return True


def commit_local(outdir: Path, description: str, *, mode: str, branch: str) -> None:
    """:DIRS-staged local commit pipeline: README -> LFS -> apps -> groups -> extras."""
    _commit_if_staged(outdir, f"Add README.md for {description}", "README.md")

    git("lfs", "install", cwd=outdir)
    _track_large_files(outdir, mode)

    if (outdir / ".gitattributes").is_file():
        _commit_if_staged(outdir, "Setup Git LFS", ".gitattributes")

    apks = sorted(str(p) for p in outdir.rglob("*.apk") if p.is_file())
    if apks:
        _commit_if_staged(outdir, f"Add apps for {description}", *apks)

    for group in _PARTITION_GROUPS:
        paths: list[str] = []
        for prefix in ("", "system/", "system/system/", "vendor/"):
            candidate = outdir / prefix / group
            if candidate.is_dir():
                paths.append(str(prefix + group))
        if paths:
            _commit_if_staged(outdir, f"Add {group} for {description}", *paths)

    _commit_if_staged(outdir, f"Add extras for {description}", ".")


def push_all(outdir: Path, branch: str) -> None:
    """Push the committed branch and its LFS objects to origin with retries."""
    if not retry_push(outdir, "-u", "origin", branch, max_attempts=5):
        raise PushError("branch push failed")
    push_lfs_objects(outdir)


def _track_large_files(outdir: Path, mode: str) -> None:
    lfs_size = _LFS_SIZES.get(mode, _LFS_SIZES["gitlab"])
    always_track = mode == "github"
    if not always_track and (outdir / ".gitattributes").is_file():
        return
    tracked = sorted(
        {
            p.name
            for p in outdir.rglob("*")
            if p.is_file() and ".git" not in p.parts and p.stat().st_size > lfs_size
        }
    )
    for name in tracked:
        git("lfs", "track", name, cwd=outdir)


def http_request(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    payload: dict | None = None,
    timeout: float = 60,
) -> tuple[int, str]:
    """urllib request; returns (status, body). Non-2xx is not an exception."""
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers=headers or {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        logger = __import__("loguru").logger
        logger.warning("HTTP {} {} -> {}: {}", method, url, exc.code, body[:200])
        return exc.code, body
    except urllib.error.URLError as exc:
        logger = __import__("loguru").logger
        logger.warning("HTTP {} {} -> {}", method, url, exc.reason)
        return 0, str(exc.reason)


__all__ = [
    "PushError",
    "commit_local",
    "git",
    "http_request",
    "init_repo",
    "push_all",
    "push_lfs_objects",
    "retry_push",
]
