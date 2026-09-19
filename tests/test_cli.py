"""Group 13: cli.py flag parity + main() wiring order with mocked phases."""

from __future__ import annotations

import pytest
import rich_click as click

from dumprx import cli
from dumprx.cli import cli as cli_cmd


def _parsed(argv: list[str]) -> dict:
    return cli_cmd.make_context("dumprx", argv).params


def test_parser_defaults():
    params = _parsed([])
    assert params["mode"] == "gitlab"  # bash default
    assert params["visibility"] == "private"
    assert params["push_only"] is False
    assert params["readme_only"] is False
    assert params["setup"] is False
    assert params["no_setup"] is False
    assert params["output"] is None
    assert params["firmware"] is None


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
    params = _parsed(argv)
    assert params["mode"] == mode
    assert params["visibility"] == visibility
    assert params["push_only"] is push
    assert params["readme_only"] is readme


@pytest.mark.parametrize("argv", [["-m", "bogus"], ["--bogus"]])
def test_invalid_option_rejected(argv):
    with pytest.raises(click.UsageError):
        _parsed(argv)


def test_missing_input_gates_error(monkeypatch):
    """main() without firmware and without push/readme flags exits 1."""

    def fake_build_config(**kw):
        calls.append(kw)
        return real_build_config(**kw)

    monkeypatch.setattr(cli, "bootstrap", lambda *a, **k: None)
    calls: list[dict] = []
    real_build_config = cli.build_config
    monkeypatch.setattr(cli, "build_config", fake_build_config)
    monkeypatch.setattr(cli, "setup_complete", lambda: True)
    assert cli.main(["--no-setup"]) == 1
    assert calls[0]["push_only"] is False and calls[0]["readme_only"] is False


class _Info:
    def __init__(self):
        self.manufacturer = "X"
        self.codename = "a"
        self.description = "flavor 13 TP1A 123 test"
        self.branch = "flavor-13-TP1A-123-test"
        self.incremental = "123"
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
                "settings": Settings(**{k: v for k, v in kw.items() if k != "outdir"}),
                "secrets": type("Sec", (), {"tg_token": "tok"}),
                "log_level": "DEBUG",
            },
        )()

    monkeypatch.setattr(cli, "build_config", fake_config)
    monkeypatch.setattr(cli, "bootstrap", lambda *a, **k: None)
    monkeypatch.setattr(cli, "setup_complete", lambda: True)
    calls = []
    from dumprx.pipeline import PipelineResult

    monkeypatch.setattr(
        cli,
        "run_pipeline",
        lambda ctx: calls.append("pipeline")  # noqa: B023
        or PipelineResult(outdir=ctx.outdir, terminal="", partitions=["system"]),
    )
    monkeypatch.setattr(cli, "resolve_source", lambda src, cfg: _Resolved("file", src))
    monkeypatch.setattr(cli, "init_repo", lambda out, br, fallback_branch="": br)
    monkeypatch.setattr(cli, "commit_local", lambda *a, **k: calls.append("commit"))
    monkeypatch.setattr(cli, "_make_info", lambda config: calls.append("props") or _Info())
    monkeypatch.setattr(
        cli, "write_readme", lambda o, info: calls.append("readme") or (o / "README.md")
    )
    monkeypatch.setattr(cli, "generate_twrp", lambda *a, **k: calls.append("twrp"))
    import dumprx.notify as notify_mod

    monkeypatch.setattr(
        notify_mod,
        "send_tg_event",
        lambda config, text, *, min_level="normal": calls.append("tg_event") or True,
    )
    monkeypatch.setattr(
        notify_mod, "send_tg_alert", lambda config, text: calls.append("tg_alert") or True
    )
    return calls


def test_readme_only_skips_pipeline(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path, ["-r"])
    rc = cli.main(["-r", "--no-setup"])
    assert rc == 0
    assert "pipeline" not in calls  # extraction skipped
    assert calls == ["props", "readme"]


def test_main_local_phase_order(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path, ["-m", "local"])
    rc = cli.main(["-m", "local", str(tmp_path / "f.bin"), "--no-setup"])
    assert rc == 0
    assert calls == ["tg_event", "pipeline", "tg_event", "props", "readme", "twrp", "commit", "tg_event"]


def test_main_gitlab_phase_order(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path, ["--gitlab"])

    def fake_publish(config, info, branch):
        calls.append("publish")
        assert info.branch == branch  # effective branch (typed) propagates

    monkeypatch.setattr(cli, "_notify", lambda *a, **k: calls.append("notify"))
    import dumprx.publishers as pubmod

    monkeypatch.setattr(pubmod, "publish", fake_publish)
    rc = cli.main(["--gitlab", "--push-only", "--no-setup"])
    assert rc == 0
    assert calls == ["props", "readme", "twrp", "commit", "tg_event", "publish", "notify"]


def test_main_publish_failure_returns_1(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path, ["--gitlab"])
    import dumprx.publishers as pubmod

    def boom(config, info, branch):
        calls.append("publish")
        raise RuntimeError("auth failed")

    monkeypatch.setattr(pubmod, "publish", boom)
    rc = cli.main(["--gitlab", "--push-only", "--no-setup"])
    assert rc == 1
    assert calls[-1] == "tg_alert"  # publish failure triggers an always-on alert


def test_main_local_commit_uses_gitlab_lfs_sizing(monkeypatch, tmp_path):
    """Local mode commits with gitlab LFS thresholds; no publisher, no notify."""
    calls = _setup(monkeypatch, tmp_path, ["-m", "local"])
    seen: dict = {}

    def fake_commit_local(outdir, description, *, mode, branch):
        calls.append("commit")
        seen.update(mode=mode, branch=branch)

    monkeypatch.setattr(cli, "commit_local", fake_commit_local)
    monkeypatch.setattr(cli, "init_repo", lambda out, br, fallback_branch="": "fb-branch")
    monkeypatch.setattr(cli, "_notify", lambda *a, **k: calls.append("notify"))
    rc = cli.main(["-m", "local", str(tmp_path / "f.bin"), "--no-setup"])
    assert rc == 0
    assert seen["mode"] == "gitlab"  # local uses 100 MB LFS thresholds
    assert seen["branch"] == "fb-branch"  # effective branch (with fallback) reaches commit
    assert "notify" not in calls


def test_main_gitlab_missing_token_aborts_after_local_commit(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path, ["--gitlab"])
    import dumprx.publishers as pubmod

    def boom(config, info, branch):
        calls.append("publish")
        raise pubmod.PushError("GitLab mode selected but gitlab token is missing.")

    monkeypatch.setattr(pubmod, "publish", boom)
    rc = cli.main(["--gitlab", "--push-only", "--no-setup"])
    assert rc == 1
    assert "commit" in calls  # dump was committed before the token abort
    assert "notify" not in calls


def _readme_fake(o, info):
    o.mkdir(parents=True, exist_ok=True)
    (o / "README.md").write_text("ok\n", encoding="utf-8")
    return o / "README.md"


def test_output_flag_reaches_build_config(monkeypatch, tmp_path):
    kw_calls: list[dict] = []
    monkeypatch.setattr(cli, "bootstrap", lambda *a, **k: None)
    monkeypatch.setattr(cli, "setup_complete", lambda: True)
    monkeypatch.setattr(cli, "_make_info", lambda config: _Info())
    monkeypatch.setattr(cli, "write_readme", _readme_fake)

    def fake_build_config(**kw):
        kw_calls.append(kw)
        from dumprx.config import Config, Paths, Settings

        return Config(paths=Paths(tmp_path, tmp_path / "input", tmp_path / "utils"), settings=Settings(mode=kw["mode"]))

    monkeypatch.setattr(cli, "build_config", fake_build_config)
    assert cli.main(["-r", "--no-setup", "-o", str(tmp_path)]) == 0
    assert kw_calls[0]["outdir"] == tmp_path

    kw_calls.clear()
    assert cli.main(["-r", "--no-setup"]) == 0
    assert kw_calls[0]["outdir"] is None


def test_push_only_with_output(monkeypatch, tmp_path):
    kw_calls: list[dict] = []

    def fake_build_config(**kw):
        kw_calls.append(kw)
        from dumprx.config import Config, Paths, Settings

        return Config(
            paths=Paths(tmp_path, tmp_path / "input", tmp_path / "utils"),
            settings=Settings(**{k: v for k, v in kw.items() if k != "outdir"}),
        )

    monkeypatch.setattr(cli, "build_config", fake_build_config)
    monkeypatch.setattr(cli, "bootstrap", lambda *a, **k: None)
    monkeypatch.setattr(cli, "setup_complete", lambda: True)
    monkeypatch.setattr(cli, "_make_info", lambda config: _Info())
    monkeypatch.setattr(cli, "write_readme", _readme_fake)
    monkeypatch.setattr(cli, "generate_twrp", lambda *a, **k: None)
    monkeypatch.setattr(cli, "init_repo", lambda out, br, fallback_branch="": br)
    monkeypatch.setattr(cli, "commit_local", lambda *a, **k: None)
    out = tmp_path / "dumps"
    assert cli.main(["--push-only", "--no-setup", "-m", "local", "-o", str(out)]) == 0
    assert kw_calls[0]["outdir"] == out
    assert kw_calls[0]["push_only"] is True


def test_help_exits_zero():
    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(cli_cmd, ["--help"])
    assert result.exit_code == 0
    assert "--setup" in result.output
    assert "--no-setup" in result.output
    assert "--output" in result.output
    assert "--force" in result.output
    assert "Mode" in result.output
    assert "Setup" in result.output


def _tg_cfg(tmp_path, verbosity="normal"):
    from dumprx.config import Config, Paths, Secrets, Settings

    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    return Config(
        paths=Paths(tmp_path, tmp_path / "input", tmp_path / "utils", out),
        settings=Settings(tg_verbosity=verbosity),
        secrets=Secrets(tg_token="tok"),
    )


@pytest.mark.parametrize("verbosity", ["normal", "verbose"])
def test_extraction_and_commit_messages(monkeypatch, tmp_path, verbosity):
    msgs = []
    cfg = _tg_cfg(tmp_path, verbosity)
    monkeypatch.setattr(cli, "build_config", lambda **kw: cfg)
    monkeypatch.setattr(cli, "bootstrap", lambda *a, **k: None)
    monkeypatch.setattr(cli, "setup_complete", lambda: True)
    monkeypatch.setattr(cli, "resolve_source", lambda src, cfg: _Resolved("file", src))
    monkeypatch.setattr(cli, "init_repo", lambda out, br, fallback_branch="": "flavor-br")
    monkeypatch.setattr(cli, "commit_local", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_make_info", lambda config: _Info())
    monkeypatch.setattr(cli, "write_readme", _readme_fake)
    monkeypatch.setattr(cli, "generate_twrp", lambda *a, **k: None)

    import dumprx.notify as notify_mod

    monkeypatch.setattr(
        notify_mod,
        "send_tg_event",
        lambda config, text, *, min_level="normal": msgs.append((min_level, text)) or True,
    )
    monkeypatch.setattr(notify_mod, "send_tg_alert", lambda config, text: msgs.append(("alert", text)) or True)

    from dumprx.pipeline import PipelineResult

    monkeypatch.setattr(
        cli,
        "run_pipeline",
        lambda ctx: PipelineResult(outdir=ctx.outdir, terminal="", partitions=["system", "vendor"]),
    )

    rc = cli.main(["-m", "local", str(tmp_path / "firmware&1.bin"), "--no-setup"])
    assert rc == 0

    started = [t for lvl, t in msgs if "extraction started" in t]
    assert started and "firmware&amp;1.bin" in started[0]  # source name, HTML-escaped
    finished = [t for lvl, t in msgs if "extraction finished" in t]
    assert finished and "2 partitions" in finished[0]
    committed = [t for lvl, t in msgs if "committed locally" in t]
    assert committed and str(tmp_path / "out") in committed[0]
    assert (" after " in finished[0]) == (verbosity == "verbose")
    assert ("branch flavor-br" in committed[0]) == (verbosity == "verbose")


def test_final_card_sent_at_minimal_threshold(monkeypatch, tmp_path):
    msgs = []
    import dumprx.notify as notify_mod

    monkeypatch.setattr(
        notify_mod,
        "send_tg_event",
        lambda config, text, *, min_level="normal": msgs.append(min_level) or True,
    )
    from dumprx.props.models import FirmwareInfo

    info = FirmwareInfo(manufacturer="X", codename="a", description="d", branch="b")
    cli._notify(_tg_cfg(tmp_path, verbosity="minimal"), info, "https://g/tree/x/", "gitlab")
    assert msgs == ["minimal"]


def test_pipeline_failure_alerts(monkeypatch, tmp_path):
    alerts = []
    _setup(monkeypatch, tmp_path, ["--gitlab"])
    import dumprx.notify as notify_mod

    monkeypatch.setattr(notify_mod, "send_tg_alert", lambda config, text: alerts.append(text) or True)

    from dumprx.process import ProcessError

    def boom(ctx):
        raise ProcessError("boom")

    monkeypatch.setattr(cli, "run_pipeline", boom)
    rc = cli.main(["--gitlab", str(tmp_path / "f.bin"), "--no-setup"])
    assert rc == 1
    assert alerts and "pipeline failed" in alerts[0] and "boom" in alerts[0]


def test_prop_error_alerts(monkeypatch, tmp_path):
    alerts = []
    _setup(monkeypatch, tmp_path, ["--gitlab"])
    import dumprx.notify as notify_mod

    monkeypatch.setattr(notify_mod, "send_tg_alert", lambda config, text: alerts.append(text) or True)

    def boom(config):
        raise cli.PropError("no props")

    monkeypatch.setattr(cli, "_make_info", boom)
    rc = cli.main(["--gitlab", "--push-only", "--no-setup"])
    assert rc == 1
    assert alerts and "property parse failed" in alerts[0]


def test_commit_failure_alerts(monkeypatch, tmp_path):
    alerts = []
    _setup(monkeypatch, tmp_path, ["--gitlab"])
    import dumprx.notify as notify_mod

    monkeypatch.setattr(notify_mod, "send_tg_alert", lambda config, text: alerts.append(text) or True)

    def boom(*a, **k):
        raise RuntimeError("index lock")

    monkeypatch.setattr(cli, "commit_local", boom)
    rc = cli.main(["--gitlab", "--push-only", "--no-setup"])
    assert rc == 1
    assert alerts and "local commit failed" in alerts[0]


def test_publish_failure_alert_mentions_preserved_dump(monkeypatch, tmp_path):
    alerts = []
    calls = _setup(monkeypatch, tmp_path, ["--gitlab"])
    import dumprx.notify as notify_mod

    monkeypatch.setattr(notify_mod, "send_tg_alert", lambda config, text: alerts.append(text) or True)

    import dumprx.publishers as pubmod

    def boom(config, info, branch):
        calls.append("publish")
        raise RuntimeError("auth failed")

    monkeypatch.setattr(pubmod, "publish", boom)
    rc = cli.main(["--gitlab", "--push-only", "--no-setup"])
    assert rc == 1
    assert alerts and "publish failed" in alerts[0]
    assert str(tmp_path / "out") in alerts[0]  # dump preserved for re-push
