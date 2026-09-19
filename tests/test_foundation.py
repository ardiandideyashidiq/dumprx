"""Tests for foundation modules: config, logger, process."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from dumprx import config as cfg
from dumprx.config import Config, Paths, Secrets, build_config
from dumprx.logger import bootstrap
from dumprx.process import ProcessError, ProcessTimeout, run


def write_env(tmp_path: Path, body: str) -> Path:
    f = tmp_path / ".dumprxenv"
    f.write_text(body, encoding="utf-8")
    return f


def test_secrets_repr_redacts():
    s = Secrets(gitlab_token="SUPER-SECRET-TOKEN", github_token="GH-SECRET")
    assert "SUPER-SECRET-TOKEN" not in repr(s)
    assert "SUPER-SECRET-TOKEN" not in str(s)
    assert s.as_log_safe_dict()["has_gitlab_token"] is True
    assert "SUPER-SECRET-TOKEN" not in repr(s.as_log_safe_dict())


def test_config_never_serializes_tokens(tmp_path):
    write_env(tmp_path, 'export GITLAB_TOKEN="abc123"\nexport TG_TOKEN="xyz"\n')
    conf = build_config(project_dir=tmp_path)
    formatted = repr(conf)
    assert "abc123" not in formatted
    assert "xyz" not in formatted
    assert conf.secrets.gitlab_token == "abc123"


def test_env_file_parsing(tmp_path):
    write_env(
        tmp_path,
        '# comment\nGITHUB_ORG="MyOrg"\nTG_CHAT=@chan\nexport GITLAB_TOKEN=tok\n\n',
    )
    data = cfg.load_env_file(tmp_path / ".dumprxenv")
    assert data == {"GITHUB_ORG": "MyOrg", "TG_CHAT": "@chan", "GITLAB_TOKEN": "tok"}


def test_partitions_tables():
    assert "system" in cfg.PARTITIONS
    assert "vendor_boot" in cfg.NO_FS_PARTITIONS
    assert "system" in cfg.EXT4_PARTITIONS
    assert cfg.OTHER_PARTITIONS["modem.img"] == "modem"


def test_jobs_env_override(tmp_path):
    os.environ["DUMPRX_JOBS"] = "7"
    try:
        conf = build_config(project_dir=tmp_path)
        assert conf.settings.jobs == 7
    finally:
        del os.environ["DUMPRX_JOBS"]


def test_config_missing_env_file_defaults(tmp_path):
    conf = build_config(project_dir=tmp_path)
    assert conf.secrets.gitlab_instance == "gitlab.com"
    assert conf.settings.mode == "gitlab"
    assert conf.settings.visibility == "private"


def test_paths_derived(tmp_path):
    conf = build_config(project_dir=tmp_path)
    assert conf.paths.inputdir == tmp_path / "input"
    assert conf.paths.utilsdir == tmp_path / "utils"
    assert str(conf.paths.outdir).endswith("out")
    assert conf.paths.workdir == conf.paths.outdir / "tmp"


def _file_backoff_contains(path: Path, needle: str, times: int = 50):
    for _ in range(times):
        if path.exists() and needle in path.read_text(encoding="utf-8"):
            return True
        time.sleep(0.02)
    return False


def test_file_sink_and_level_override(tmp_path):
    log_file = tmp_path / "dumprx.log"
    bootstrap(level="DEBUG", log_file=log_file)

    from loguru import logger

    logger.debug("dbg line marker 1234")
    assert _file_backoff_contains(log_file, "dbg line marker 1234")
    assert "dbg line marker 1234" in log_file.read_text(encoding="utf-8")

    log_file2 = tmp_path / "dumprx-info.log"
    bootstrap(level="INFO", log_file=log_file2)
    logger.debug("should be filtered 9876")
    logger.info("info line marker 5555")
    assert _file_backoff_contains(log_file2, "info line marker 5555")
    assert not _file_backoff_contains(log_file2, "should be filtered 9876")


def test_process_success_and_capture():
    res = run(["python3", "-c", "print('hello')"], capture=True)
    assert res.ok
    assert res.stdout_text.strip() == "hello"


def test_process_nonzero_tolerated():
    res = run(["python3", "-c", "import sys; sys.exit(3)"], capture=True)
    assert res.returncode == 3
    assert not res.ok


def test_process_check_raises():
    with pytest.raises(ProcessError):
        run(["python3", "-c", "import sys; sys.exit(1)"], check=True)


def test_process_timeout():
    with pytest.raises(ProcessTimeout):
        run(["python3", "-c", "import time; time.sleep(30)"], timeout=0.3)


def test_process_missing_binary():
    with pytest.raises(ProcessError):
        run(["/nonexistent/definitely-not-here-xyz"], capture=True)


def _fd_count() -> int:
    return len(os.listdir("/proc/self/fd"))


def test_no_fd_leak_loop():
    before = _fd_count()
    for _ in range(100):
        run(["true"], capture=True)
    run(["python3", "-c", "print('x'*5000)"], capture=True)
    for _ in range(50):
        run(["true"])
    assert _fd_count() <= before + 5


def test_streaming_input_supported():
    res = run(["cat"], input_data=b"via-stdin\n", capture=True)
    assert res.stdout_text == "via-stdin\n"


def test_paths_and_config_frozen():
    p = Paths(project_dir=Path("/x"), inputdir=Path("/x/input"), utilsdir=Path("/x/utils"))
    with pytest.raises(Exception):
        p.inputdir = Path("/y")  # type: ignore[misc]
    conf = Config(paths=p, settings=cfg.Settings())
    with pytest.raises(Exception):
        conf.settings = cfg.Settings(mode="local")  # type: ignore[misc]
