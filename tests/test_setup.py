"""Group: setup.py unit tests + CLI setup-state gating."""

from __future__ import annotations

import json
import os

import pytest

from dumprx import cli
from dumprx import setup as setupmod


def test_state_path_default():
    expected = (setupmod.Path.home() / ".local" / "state" / "dumprx" / "state.json")
    saved = os.environ.pop("XDG_STATE_HOME", None)
    try:
        assert setupmod.state_path() == expected
    finally:
        if saved is not None:
            os.environ["XDG_STATE_HOME"] = saved


def test_state_path_override(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert setupmod.state_path() == tmp_path / "dumprx" / "state.json"


def test_setup_complete_requires_full_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(setupmod, "state_path", lambda: tmp_path / "state.json")
    assert setupmod.setup_complete() is False  # missing file
    setupmod.mark_complete("apt")
    assert setupmod.setup_complete() is True
    data = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert data["complete"] is True
    assert data["pm"] == "apt"
    (tmp_path / "state.json").write_text(json.dumps({"complete": False}), encoding="utf-8")
    assert setupmod.setup_complete() is False  # incomplete marker
    (tmp_path / "state.json").write_text("not json", encoding="utf-8")
    assert setupmod.setup_complete() is False  # corrupt file


@pytest.mark.parametrize("manager", ["apt", "dnf", "pacman", "apk", "brew"])
def test_detect_package_manager(monkeypatch, manager):
    monkeypatch.setattr(
        setupmod.shutil, "which", lambda name: f"/usr/bin/{name}" if name == manager else None
    )
    assert setupmod.detect_package_manager() == manager


def test_detect_package_manager_none(monkeypatch):
    monkeypatch.setattr(setupmod.shutil, "which", lambda name: None)
    assert setupmod.detect_package_manager() is None


def test_package_lists_present():
    for manager, packages in setupmod._PACKAGES.items():
        assert packages, manager
    assert "p7zip-full" in setupmod._PACKAGES["apt"]
    assert "git-lfs" in setupmod._PACKAGES["apt"]
    assert "detox" in setupmod._PACKAGES["brew"]


def test_run_visible_ok():
    assert setupmod.run_visible(["true"]) == 0


def test_run_visible_failure():
    with pytest.raises(RuntimeError):
        setupmod.run_visible(["false"])


def test_install_uv_sudo_user(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(setupmod.shutil, "which", lambda name: "/usr/bin/sudo" if name == "sudo" else None)
    monkeypatch.setitem(os.environ, "SUDO_USER", "alice")
    monkeypatch.setattr(setupmod, "run_visible", lambda argv: calls.append(argv) or 0)
    setupmod.install_uv()
    assert calls[0][:3] == ["sudo", "-u", "alice"]
    assert calls[0][3:] == ["bash", "-c", f"curl -sL {setupmod.UV_INSTALL_URL} | bash"]


def test_install_uv_no_sudo(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.delenv("SUDO_USER", raising=False)
    monkeypatch.setattr(setupmod, "run_visible", lambda argv: calls.append(argv) or 0)
    setupmod.install_uv()
    assert calls[0] == ["bash", "-c", f"curl -sL {setupmod.UV_INSTALL_URL} | bash"]


def test_install_system_packages_apt(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(setupmod, "run_visible", lambda argv: calls.append(argv) or 0)
    monkeypatch.setattr(setupmod, "_sudo_prefix", lambda: ["sudo"])
    setupmod.install_system_packages("apt")
    assert calls[0] == ["sudo", "apt", "-y", "update"]
    assert calls[1][:4] == ["sudo", "apt", "install", "-y"]
    assert "p7zip-full" in calls[1]


def test_run_setup_explicit_failure(monkeypatch):
    def boom(pm):
        raise RuntimeError("apt exploded")

    monkeypatch.setattr(setupmod, "detect_package_manager", lambda: "apt")
    monkeypatch.setattr(setupmod, "install_system_packages", boom)
    assert setupmod.run_setup(object(), explicit=True) == 1


def test_run_setup_auto_failure_warns(monkeypatch):
    def boom():
        raise RuntimeError("network down")

    monkeypatch.setattr(setupmod, "detect_package_manager", lambda: None)
    monkeypatch.setattr(setupmod, "install_uv", boom)
    assert setupmod.run_setup(object(), explicit=False) == 0


def test_run_setup_success(monkeypatch, tmp_path):
    calls: list = []
    monkeypatch.setattr(setupmod, "detect_package_manager", lambda: "brew")
    monkeypatch.setattr(setupmod, "install_system_packages", lambda pm: calls.append(pm))
    monkeypatch.setattr(setupmod, "install_uv", lambda: calls.append("uv"))
    monkeypatch.setattr(setupmod, "ensure_runtime_clones", lambda d: calls.append(d))
    monkeypatch.setattr(setupmod, "run_visible", lambda a, **kw: calls.append(("sync", a)) or 0)
    monkeypatch.setattr(setupmod, "mark_complete", lambda pm: calls.append(("done", pm)))

    class _Paths:
        utilsdir = tmp_path / "utils"
        project_dir = tmp_path

    assert setupmod.run_setup(type("C", (), {"paths": _Paths()})(), explicit=True) == 0
    assert calls == [
        "brew",
        "uv",
        tmp_path / "utils",
        ("sync", ["uv", "sync"]),
        ("done", "brew"),
    ]


def test_mark_complete_readonly_dir(tmp_path, monkeypatch):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o555)
    try:
        monkeypatch.setattr(setupmod, "state_path", lambda: ro / "state.json")
        setupmod.mark_complete("apt")  # must not raise
    finally:
        ro.chmod(0o755)


class _Config:
    def __init__(self, tmp_path):
        self.paths = type("P", (), {"outdir": tmp_path / "out"})()


def _setup_cli(monkeypatch, tmp_path):
    from dumprx.config import Paths, Settings

    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "README.md").write_text("ok\n", encoding="utf-8")

    def fake_config(**kw):
        return type(
            "Config",
            (),
            {
                "paths": Paths(tmp_path, tmp_path / "input", tmp_path / "utils", out),
                "settings": Settings(**{k: v for k, v in kw.items() if k != "outdir"}),
                "secrets": type("Sec", (), {"tg_token": "tok"}),
            },
        )()

    monkeypatch.setattr(cli, "build_config", fake_config)
    monkeypatch.setattr(cli, "bootstrap", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_make_info", lambda config: type(
        "I", (), {"manufacturer": "X", "codename": "a", "description": "d", "branch": "b"}
    )())
    monkeypatch.setattr(cli, "write_readme", lambda o, info: o / "README.md")
    monkeypatch.setattr(cli, "generate_twrp", lambda *a, **k: None)


def test_main_state_gate_missing_state(monkeypatch, tmp_path):
    _setup_cli(monkeypatch, tmp_path)
    calls: list[bool] = []
    monkeypatch.setattr(cli, "setup_complete", lambda: False)

    def fake_run_setup(config, *, explicit=False):
        calls.append(explicit)
        return 0

    monkeypatch.setattr(cli, "run_setup", fake_run_setup)
    assert cli.main(["-r", "-m", "local"]) == 0
    assert calls == [False]  # auto-run happened


def test_main_state_gate_complete(monkeypatch, tmp_path):
    _setup_cli(monkeypatch, tmp_path)
    calls: list[bool] = []
    monkeypatch.setattr(cli, "setup_complete", lambda: True)
    monkeypatch.setattr(cli, "run_setup", lambda config, *, explicit=False: calls.append(explicit) or 0)
    assert cli.main(["-r", "-m", "local"]) == 0
    assert calls == []  # skipped


def test_main_no_setup_bypasses_gate(monkeypatch, tmp_path):
    _setup_cli(monkeypatch, tmp_path)
    calls: list[bool] = []
    monkeypatch.setattr(cli, "setup_complete", lambda: False)
    monkeypatch.setattr(cli, "run_setup", lambda config, *, explicit=False: calls.append(explicit) or 0)
    assert cli.main(["-r", "-m", "local", "--no-setup"]) == 0
    assert calls == []  # bypassed


def test_main_explicit_setup_runs_and_exits(monkeypatch, tmp_path):
    _setup_cli(monkeypatch, tmp_path)
    calls: list[bool] = []
    monkeypatch.setattr(cli, "run_setup", lambda config, *, explicit=False: calls.append(explicit) or 0)
    assert cli.main(["--setup"]) == 0
    assert calls == [True]  # explicit, no firmware required


def test_main_explicit_setup_failure_exits_1(monkeypatch, tmp_path):
    _setup_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "run_setup", lambda config, *, explicit=False: 1)
    assert cli.main(["--setup"]) == 1


def test_main_auto_setup_failure_continues(monkeypatch, tmp_path):
    _setup_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "setup_complete", lambda: False)
    monkeypatch.setattr(cli, "run_setup", lambda config, *, explicit=False: 0)
    assert cli.main(["-r", "-m", "local"]) == 0  # warn-and-continue
