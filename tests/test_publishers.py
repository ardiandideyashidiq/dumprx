"""Group 12: publishers/base.py (retry, LFS) + gitlab.py / github.py API flows."""

from __future__ import annotations

import json

from dumprx.config import Secrets, build_config
from dumprx.props.models import FirmwareInfo
from dumprx.publishers import base
from dumprx.publishers import github as gh
from dumprx.publishers import gitlab as gl
from dumprx.publishers.base import PushError, commit_and_push, push_lfs_objects, retry_push


class _R:
    def __init__(self, code, out=b""):
        self.returncode = code
        self.qid = None
        self.stdout = out
        self.stderr = b""

    @property
    def ok(self):
        return self.returncode == 0

    @property
    def stdout_text(self):
        return self.stdout.decode("utf-8", errors="replace")


def _info(codename="X6878", manufacturer="Infinix", description="flavor 13 x x tags"):
    return FirmwareInfo(codename=codename, manufacturer=manufacturer, description=description)


def test_github_repo_name_preserves_casing(tmp_path):
    assert gh._repo_name("X6878") == "X6878_dump"
    assert gh._repo_name("Infinix NOTE 30") == "Infinix-NOTE-30_dump"


def test_github_already_dumped_raises(monkeypatch, tmp_path):
    cfg = build_config(mode="github").with_secrets(Secrets(github_token="t", github_org="x"))
    monkeypatch.setattr(gh, "_already_dumped", lambda org, repo, branch: True)
    try:
        gh.publish(cfg, _info(), "flavor-13-x-x-tags")
        raise AssertionError("expected PushError")
    except PushError as exc:
        assert "already dumped" in str(exc)


def test_github_publish_without_token_raises(tmp_path):
    cfg = build_config(mode="github")
    try:
        gh.publish(cfg, _info(), "br")
        raise AssertionError("expected PushError")
    except PushError as exc:
        assert "github token is missing" in str(exc)


def test_github_publish_api_call_sequence(monkeypatch, tmp_path):
    """Mocked API: assert org-repo creation + visibility PATCH sequence."""
    from dumprx.config import Paths

    outdir = tmp_path / "out"
    outdir.mkdir()
    cfg = build_config(mode="github", visibility="private").with_secrets(
        Secrets(github_token="tok", github_org="acme")
    )
    cfg = cfg.with_paths(
        Paths(
            project_dir=tmp_path,
            inputdir=tmp_path / "input",
            utilsdir=tmp_path / "utils",
            outdir=outdir,
        )
    )
    (outdir / "README.md").write_text("x")
    calls = []

    def fake_http(url, *, headers=None, method="GET", payload=None, timeout=60):
        calls.append((method, url))
        if url.startswith("https://raw.githubusercontent.com"):
            return 404, "not found"
        return 200, json.dumps({"name": "X6878_dump", "id": 1})

    monkeypatch.setattr(gh, "http_request", fake_http)
    monkeypatch.setattr(gh, "git", lambda *a, **k: _R(0))
    monkeypatch.setattr(gh, "commit_and_push", lambda *a, **k: None)
    monkeypatch.setattr(gh, "init_repo", lambda out, br, fallback_branch="": br)

    url = gh.publish(cfg, _info(), "branch-x")
    assert url == "https://github.com/acme/X6878_dump/tree/branch-x/"
    # GITHUB_ORG set -> org-scoped create, not user repos
    assert ("POST", "https://api.github.com/orgs/acme/repos") in calls
    assert not any(u.endswith("/user/repos") for m, u in calls)
    # one PATCH per phase: description+visibility, then default_branch
    patches = [u for m, u in calls if m == "PATCH"]
    assert patches == [
        "https://api.github.com/repos/acme/X6878_dump",
        "https://api.github.com/repos/acme/X6878_dump",
    ]


def test_github_publish_user_scoped_create(monkeypatch, tmp_path):
    from dumprx.config import Paths

    outdir = tmp_path / "out"
    outdir.mkdir()
    cfg = build_config(mode="github").with_secrets(Secrets(github_token="tok"))
    cfg = cfg.with_paths(
        Paths(
            project_dir=tmp_path,
            inputdir=tmp_path / "input",
            utilsdir=tmp_path / "utils",
            outdir=outdir,
        )
    )
    (outdir / "README.md").write_text("x")
    calls = []

    def fake_http(url, *, headers=None, method="GET", payload=None, timeout=60):
        calls.append((method, url))
        if url == "https://api.github.com/user":
            return 200, json.dumps({"login": "bondan"})
        if url.startswith("https://raw.githubusercontent.com"):
            return 404, "not found"
        return 200, json.dumps({"name": "X6878_dump", "id": 1})

    monkeypatch.setattr(gh, "http_request", fake_http)
    monkeypatch.setattr(gh, "git", lambda *a, **k: _R(0))
    monkeypatch.setattr(gh, "commit_and_push", lambda *a, **k: None)
    monkeypatch.setattr(gh, "init_repo", lambda out, br, fallback_branch="": br)

    url = gh.publish(cfg, _info(), "branch-x")
    assert url == "https://github.com/bondan/X6878_dump/tree/branch-x/"
    assert ("GET", "https://api.github.com/user") in calls
    assert ("POST", "https://api.github.com/user/repos") in calls


def test_gitlab_publish_api_sequence(monkeypatch, tmp_path):
    from dumprx.config import Paths

    outdir = tmp_path / "out"
    outdir.mkdir()
    cfg = build_config(mode="gitlab").with_secrets(
        Secrets(gitlab_token="tok", gitlab_group="grp")
    )
    cfg = cfg.with_paths(Paths(project_dir=tmp_path, inputdir=tmp_path / "input", utilsdir=tmp_path / "utils", outdir=outdir))
    (outdir / "README.md").write_text("x")
    calls = []

    def fake_http(url, *, headers=None, method="GET", payload=None, timeout=60):
        calls.append((method, url))
        if url.endswith("/-/raw/br/all_files.txt"):
            return 404, "no"
        if url == "https://gitlab.com/api/v4/groups/grp":
            return 200, json.dumps({"id": 7})
        if url == "https://gitlab.com/api/v4/groups/grp/subgroups":
            return 200, json.dumps([{"name": "Infinix", "id": 11}])
        if url == "https://gitlab.com/api/v4/groups/11/projects":
            return 200, json.dumps([{"name": "X6878", "id": 22}])
        return 201, "{}"

    monkeypatch.setattr(gl, "http_request", fake_http)
    monkeypatch.setattr(gl, "git", lambda *a, **k: _R(0))
    monkeypatch.setattr(gl, "commit_and_push", lambda *a, **k: None)
    monkeypatch.setattr(gl, "init_repo", lambda out, br, fallback_branch="": br)

    url = gl.publish(cfg, _info(), "br")
    assert url == "https://gitlab.com/grp/Infinix/X6878/-/tree/br/"
    post_urls = [u for m, u in calls if m == "POST"]
    assert post_urls == [
        "https://gitlab.com/api/v4/groups/",
        "https://gitlab.com/api/v4/projects",
    ]
    assert ("PUT", "https://gitlab.com/api/v4/projects/22") in calls  # visibility put


def test_retry_push_gives_up_after_5(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(base, "git", lambda *a, **k: calls.append(a) or _R(1))
    import time as _t

    monkeypatch.setattr(_t, "sleep", lambda _: None)
    assert retry_push(tmp_path, "-u", "origin", "x", max_attempts=5) is False
    assert len(calls) == 5


def test_retry_push_succeeds_on_third(monkeypatch, tmp_path):
    results = [_R(1), _R(1), _R(0)]
    monkeypatch.setattr(base, "git", lambda *a, **k: results.pop(0))
    import time as _t

    monkeypatch.setattr(_t, "sleep", lambda _: None)
    assert retry_push(tmp_path, "-u", "origin", "x", max_attempts=5) is True


def test_push_lfs_objects_parses_oids_and_uses_object_id(monkeypatch, tmp_path):
    """LFS worker must run the distinct `lfs push --object-id` command (not retry_push)."""
    seen = []

    def fake_git(*args, cwd, capture=False, timeout=3600):
        seen.append(args)
        if args[:3] == ("lfs", "ls-files", "--all"):
            return _R(0, b"abc123 * file.img\n" b"def456 * other.img\n")
        return _R(0)

    monkeypatch.setattr(base, "git", fake_git)
    push_lfs_objects(tmp_path, workers=2)
    push_cmds = [a for a in seen if a[:4] == ("lfs", "push", "--object-id", "origin")]
    assert len(push_cmds) == 2
    assert ("lfs", "push", "--object-id", "origin", "abc123") in push_cmds


def test_commit_and_push_lfs_threshold_github_regenerates(tmp_path, monkeypatch):
    big = tmp_path / "system.img"
    big.write_bytes(b"\x00" * (51 * 1024 * 1024))  # > 50M
    gitcmds = []

    def fake_git(*args, cwd, capture=False, timeout=3600):
        gitcmds.append(args)
        return _R(0)

    import dumprx.publishers.base as bmod

    monkeypatch.setattr(bmod, "git", fake_git)
    monkeypatch.setattr(bmod, "push_lfs_objects", lambda out: [])
    monkeypatch.setattr(bmod, "retry_push", lambda *a, max_attempts=5: True)

    # system.img is a dir here (not file) so use a file deep path check
    (tmp_path / "x.apk").write_bytes(b"apk")
    commit_and_push(tmp_path, "desc", mode="github", branch="b")
    tracks = [a for a in gitcmds if a[:3] == ("lfs", "track", "system.img")]
    assert tracks, "50M threshold should track system.img for github mode"
