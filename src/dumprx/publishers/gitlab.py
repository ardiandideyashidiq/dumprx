"""GitLab publisher: already-dumped check, subgroup/project API, SSH push.

Ports dumper.sh lines 1549-1645. All API calls go through `http_request`
so sequencing/replies are mockable in tests without network.
"""

from __future__ import annotations

import json

from loguru import logger

from dumprx.config import Config
from dumprx.props.models import FirmwareInfo
from dumprx.publishers.base import (
    PushError,
    commit_and_push,
    git,
    http_request,
    init_repo,
)


def publish(config: Config, info: FirmwareInfo, branch: str) -> str:
    """Push OUTDIR to GitLab; returns the repo tree URL (or raises PushError)."""
    secret = config.secrets
    if not secret.gitlab_token:
        raise PushError("GitLab mode selected but gitlab token is missing.")

    org = secret.gitlab_group or _git_user_name(config)
    instance = secret.gitlab_instance or "gitlab.com"
    host = f"https://{instance}"
    repo = f"{info.manufacturer}/{info.codename}"
    token = {"PRIVATE-TOKEN": secret.gitlab_token}

    tree_url = f"{host}/{org}/{repo}/-/tree/{branch}/"
    if _already_dumped(f"{host}/{org}/{repo}", branch):
        logger.warning("Firmware already dumped! {}", tree_url)
        raise PushError(f"Firmware already dumped: {tree_url}")

    outdir = config.paths.outdir
    branch = init_repo(outdir, branch, fallback_branch=info.incremental)
    project_id = _ensure_subgroup_and_project(host, org, token, info)

    git("remote", "add", "origin", f"git@{instance}:{org}/{repo}.git", cwd=outdir)

    repo_desc = info.transname or info.codename
    logger.info("Pushing to {} via SSH... Branch: {}", host, branch)
    commit_and_push(outdir, info.description, mode="gitlab", branch=branch)

    http_request(
        f"{host}/api/v4/projects/{project_id}",
        method="PUT",
        headers=token,
        payload={"visibility": config.settings.visibility, "description": repo_desc},
    )
    http_request(
        f"{host}/api/v4/projects/{project_id}",
        method="PUT",
        headers=token,
        payload={"default_branch": branch},
    )
    return tree_url


def _git_user_name(config: Config) -> str:
    result = git("config", "--get", "user.name", capture=True, cwd=config.paths.project_dir)
    return result.stdout_text.strip() if result.ok else ""


def _already_dumped(project: str, branch: str) -> bool:
    status, body = http_request(f"{project}/-/raw/{branch}/all_files.txt")
    return status == 200 and "all_files.txt" in body


def _ensure_subgroup_and_project(
    host: str, org: str, token: dict[str, str], info: FirmwareInfo
) -> str:
    status, body = http_request(f"{host}/api/v4/groups/{org}", headers=token)
    if status != 200:
        raise PushError(f"Could not find GitLab group '{org}'. Check GITLAB_GROUP in .dumprxenv")
    try:
        group_id = json.loads(body)["id"]
    except (KeyError, json.JSONDecodeError) as exc:
        raise PushError(f"Malformed group response for '{org}'") from exc

    mfr = info.manufacturer or ""
    mfr_lower = mfr.lower()
    http_request(
        f"{host}/api/v4/groups/",
        method="POST",
        headers={**token, "Content-Type": "application/json"},
        payload={"name": mfr, "path": mfr_lower, "visibility": "public", "parent_id": str(group_id)},
    )
    status, body = http_request(f"{host}/api/v4/groups/{org}/subgroups", headers=token)
    if status != 200:
        raise PushError(f"Could not list subgroups for group '{org}'")
    sub_id = ""
    for record in json.loads(body):
        if record.get("name") == mfr:
            sub_id = str(record["id"])
            break
    if not sub_id:
        raise PushError(f"Could not find subgroup for manufacturer '{mfr}'")

    http_request(
        f"{host}/api/v4/projects",
        method="POST",
        headers=token,
        payload={"name": info.codename, "namespace_id": int(sub_id), "visibility": "public"},
    )

    status, body = http_request(f"{host}/api/v4/groups/{sub_id}/projects", headers=token)
    if status != 200:
        raise PushError(f"Could not list projects in subgroup {sub_id}")
    project_id = ""
    for record in json.loads(body):
        if record.get("name") == info.codename:
            project_id = str(record["id"])
            break
    if not project_id:
        raise PushError(f"Could not find project '{info.codename}' in subgroup {sub_id}")
    return project_id


__all__ = ["publish"]
