"""Group 13: cli.py flag parity + main() wiring order with mocked phases."""

from __future__ import annotations

import pytest

from dumprx import cli
from dumprx.cli import build_parser


def test_parser_defaults():
    args = build_parser().parse_args([])
    assert args.mode == "gitlab"  # bash default
    assert args.visibility == "private"
    assert args.push_only is False
    assert args.readme_only is False
    assert args.firmware is None


@pytest.mark.parametrize(
    ("argv", "mode", "visibility", "push", "readme"),
    [
        (["--gitlab"], "gitlab", "private", False, False),
        (["--github"], "github", "private", False, False),
        (["--local"], "local", "private", False, False),
        (["-g"], "gitlab", "private", False, False),
        (["-b"], "github", "private", False, False),
        (["-l"], "local", "private", False, False),
        (["-m", "local"], "local", "private", False, False),
        (["-m", "github"], "github", "private", False, False),
        (["--public"], "gitlab", "public", False, False),
        (["-p"], "gitlab", "private", True, False),
        (["-r"], "gitlab", "private", False, True),
        (["-l", "-g"], "gitlab", "private", False, False),  # last wins (bash order)
        (["firmware.bin"], "gitlab", "private", False, False),
    ],
)
def test_flag_parity_table(argv, mode, visibility, push, readme):
    args = build_parser().parse_args(argv)
    assert args.mode == mode
    assert args.visibility == visibility
    assert args.push_only is push
    assert args.readme_only is readme


def test_invalid_mode_rejected():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["-m", "bogus"])


def test_missing_input_gates_error(monkeypatch):
    """main() without firmware and without push/readme flags exits 1 before touching disk."""
    monkeypatch.setattr(cli, "bootstrap", lambda *a, **k: None)
    calls = []
    real_build_config = cli.build_config

    def fake_build_config(*a, **k):
        calls.append(k)
        return real_build_config(*a, **k)

    monkeypatch.setattr(cli, "build_config", fake_build_config)
    assert cli.main([]) == 1
    assert calls[0]["push_only"] is False and calls[0]["readme_only"] is False


class _Info:
    def __init__(self):
        self.manufacturer = "X"
        self.codename = "a"
        self.description = "flavor 13 TP1A 123 test"
        self.branch = "flavor-13-TP1A-123-test"
        self.is_ab = "false"
        self.transname = ""


class _Resolved:
    def __init__(self, kind, path):
        self.kind = kind
        self.path = path


def _setup(monkeypatch, tmp_path, mode_flags, *, readme_only=False):
    from dumprx.config import Paths, Settings

    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "README.md").write_text("ok\n")

    def fake_config(**kw):
        return type(
            "Config",
            (),
            {
                "paths": Paths(tmp_path, tmp_path / "input", tmp_path / "utils", out),
                "settings": Settings(**kw),
                "secrets": type("Sec", (), {"tg_token": "tok"}),
                "log_level": "DEBUG",
            },
        )()

    monkeypatch.setattr(cli, "build_config", fake_config)
    monkeypatch.setattr(cli, "bootstrap", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(cli, "run_pipeline", lambda ctx: calls.append("pipeline"))
    monkeypatch.setattr(cli, "resolve_source", lambda src, cfg: _Resolved("file", src))
    monkeypatch.setattr(cli, "_make_info", lambda config: calls.append("props") or _Info())
    monkeypatch.setattr(
        cli, "write_readme", lambda o, info: calls.append("readme") or (o / "README.md")
    )
    monkeypatch.setattr(cli, "generate_twrp", lambda *a, **k: calls.append("twrp"))
    return calls


def test_readme_only_skips_pipeline(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path, ["-r"])
    rc = cli.main(["-r"])
    assert rc == 0
    assert "pipeline" not in calls  # extraction skipped
    assert calls == ["props", "readme"]


def test_main_local_phase_order(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path, ["-m", "local"])
    rc = cli.main(["-m", "local", str(tmp_path / "f.bin")])
    assert rc == 0
    assert calls == ["pipeline", "props", "readme", "twrp"]


def test_main_gitlab_phase_order(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path, ["--gitlab"])
    monkeypatch.setattr(cli, "_notify", lambda *a, **k: calls.append("notify"))
    import dumprx.publishers as pubmod

    monkeypatch.setattr(pubmod, "publish", lambda config, info, branch: calls.append("publish") or "u")
    rc = cli.main(["--gitlab", "--push-only"])
    assert rc == 0
    assert calls == ["props", "readme", "twrp", "publish", "notify"]


def test_main_publish_failure_returns_1(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path, ["--gitlab"])
    import dumprx.publishers as pubmod

    def boom(config, info, branch):
        calls.append("publish")
        raise RuntimeError("auth failed")

    monkeypatch.setattr(pubmod, "publish", boom)
    rc = cli.main(["--gitlab", "--push-only"])
    assert rc == 1
    assert calls[-1] == "publish"
