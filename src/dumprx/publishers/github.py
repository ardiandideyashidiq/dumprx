"""GitHub publisher: `_dump` naming, org vs user repos, visibility PATCH.

Ports dumper.sh lines 1646-1744. GitHub has no nested namespaces, so each
dump maps to a single repo: `{codename}_dump` (original casing, spaces
replaced with `-`).
"""

from __future__ import annotations

import json

from loguru import logger

from dumprx.config import Config
from dumprx.props.models import FirmwareInfo
from dumprx.publishers.base import (
    PushError,
    git,
    http_request,
    push_all,
)


def publish(config: Config, info: FirmwareInfo, branch: str) -> str:
    secret = config.secrets
    if not secret.github_token:
        raise PushError(
            "GitHub mode selected but github token is missing. The dump is "
            f"committed locally at {config.paths.outdir}; fill GITHUB_TOKEN in .dumprxenv and re-run to push."
        )

    org = secret.github_org or _resolve_user(secret.github_token)
    if not org:
        raise PushError(
            "Could not determine GitHub user/org from GITHUB_TOKEN/GITHUB_ORG "
            "- it may be expired, revoked, or mistyped."
        )

    gh_repo = _repo_name(info.codename)
    auth = {"Authorization": f"token {secret.github_token}", "User-Agent": "DumprX"}
    repo_api = f"https://api.github.com/repos/{org}/{gh_repo}"

    tree_url = f"https://github.com/{org}/{gh_repo}/tree/{branch}/"
    if _already_dumped(org, gh_repo, branch):
        raise PushError(f"Firmware already dumped: {tree_url}")

    outdir = config.paths.outdir

    repo_desc = info.transname or info.codename
    _create_repo(
        bool(secret.github_org), org, auth, gh_repo, repo_desc, config.settings.visibility
    )

    git("remote", "add", "origin", f"git@github.com:{org}/{gh_repo}.git", cwd=outdir)
    from dumprx.notify import esc, send_tg_event

    send_tg_event(
        config,
        f"DumprX: uploading dump to GitHub {esc(f'{org}/{gh_repo}')}...",
        min_level="normal",
    )
    logger.info("Pushing to https://github.com/{}.git via SSH... Branch: {}", org, branch)
    push_all(outdir, branch)

    public = config.settings.visibility == "public"
    http_request(
        repo_api,
        method="PATCH",
        headers=auth,
        payload={
            "description": repo_desc,
            "visibility": "public" if public else "private",
            "private": public is False,
        },
    )
    http_request(
        repo_api,
        method="PATCH",
        headers=auth,
        payload={"default_branch": branch},
    )
    return tree_url


def _resolve_user(token: str) -> str:
    status, body = http_request(
        "https://api.github.com/user",
        headers={"Authorization": f"token {token}", "User-Agent": "DumprX"},
    )
    if status != 200:
        logger.warning("GitHub authentication failed ({})", status)
        return ""
    try:
        login = json.loads(body)["login"]
    except (KeyError, json.JSONDecodeError):
        return ""
    return login or ""


def _repo_name(codename: str) -> str:
    return f"{codename.replace(' ', '-')}_dump"


def _already_dumped(org: str, repo: str, branch: str) -> bool:
    status, body = http_request(
        f"https://raw.githubusercontent.com/{org}/{repo}/{branch}/all_files.txt"
    )
    return status == 200 and "all_files.txt" in body


def _create_repo(
    org_owned: bool,
    org: str,
    auth: dict[str, str],
    name: str,
    desc: str,
    visibility: str,
) -> None:
    public = visibility == "public"
    payload = {
        "name": name,
        "description": desc,
        "visibility": "public" if public else "private",
        "private": public is False,
        "has_wiki": False,
        "has_projects": False,
    }
    if org_owned:
        url = f"https://api.github.com/orgs/{org}/repos"
    else:
        url = "https://api.github.com/user/repos"
    http_request(url, method="POST", headers=auth, payload=payload)


__all__ = ["publish"]
