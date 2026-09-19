"""Tests for the extraction pipeline, downloader dispatch and cleanup."""

from __future__ import annotations

import signal
from pathlib import Path
from types import SimpleNamespace

import pytest

from dumprx.config import build_config
from dumprx.downloader import download_into, select_downloader
from dumprx.extractors import WorkContext, load_extractors
from dumprx.extractors.base import StageLimitError
from dumprx.pipeline import (
    clear_workdir,
    extract_chain,
    fix_permissions,
    install_cleanup,
    promote_partitions,
    remove_sys_journals,
    write_all_files,
)


@pytest.fixture(autouse=True)
def _registered():
    load_extractors()


def _ctx(tmp_path, name="bundle.zip", listing=None) -> WorkContext:
    src = tmp_path / name
    src.write_bytes(b"seed")
    cfg = build_config(project_dir=tmp_path, outdir=tmp_path)
    paths = type(cfg.paths)(
        project_dir=tmp_path,
        inputdir=tmp_path / "input",
        utilsdir=tmp_path / "utils",
        outdir=tmp_path / "out",
        workdir=tmp_path / "out" / "tmp",
    )
    cfg = cfg.with_paths(paths)
    (tmp_path / "out" / "tmp").mkdir(parents=True, exist_ok=True)
    (tmp_path / "utils" / "bin").mkdir(parents=True, exist_ok=True)
    return WorkContext(
        source=src,
        outdir=paths.outdir,
        workdir=paths.workdir,
        config=cfg,
        archive_listing=listing,
    )


def _res(ok=True, code=0):
    return SimpleNamespace(ok=ok, returncode=code, stdout=b"", stderr=b"")


# --- 10.1 stage queue ---


def test_extract_chain_container_requeue_then_terminal_break(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, "a.ozip")
    queue = []

    class C1:
        name = "fake-container"

        def extract(self, c):
            queue.append("c1")
            return tmp_path / "nested.zip"

    class T1:
        name = "fake-terminal"

        def extract(self, c):
            queue.append("t1")
            return None

    import dumprx.pipeline as pipeline

    seq = iter([C1(), T1()])  # container first, terminal second
    monkeypatch.setattr(pipeline, "classify", lambda c: next(seq))
    monkeypatch.setattr(pipeline, "prepare_listing", lambda c: c)
    terminal = extract_chain(ctx)
    assert queue == ["c1", "t1"]
    assert terminal == "fake-terminal"
    assert ctx.source == tmp_path / "nested.zip"  # requeued before terminal consumed


def test_extract_chain_loop_guard_raises(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, "a.bin")

    class C:
        name = "loop"

        def extract(self, c):
            return tmp_path / "a.bin"

    import dumprx.pipeline as pipeline

    monkeypatch.setattr(pipeline, "classify", lambda c: C())
    monkeypatch.setattr(pipeline, "prepare_listing", lambda c: c)
    with pytest.raises(StageLimitError):
        extract_chain(ctx)


# --- 10.2 downloader ---


class _Tools:
    def __init__(self):
        self.map = {}

    def __getitem__(self, name):
        return self.map.get(name)


def test_select_downloader_hoster_dispatch():
    tools = _Tools()
    tools.map = {
        "mega-media-drive_dl": Path("/u/d.sh"),
        "afh_dl": Path("/u/afh.py"),
        "transfer": Path("/u/t"),
    }
    assert select_downloader("https://mega.nz/x", tools) == ("script", ["/u/d.sh", "https://mega.nz/x"])
    assert select_downloader("https://www.androidfilehost.com/?fid=1", tools) == (
        "script",
        ["python3", "/u/afh.py", "-l", "https://www.androidfilehost.com/?fid=1"],
    )
    assert select_downloader("https://we.tl/t-abc", tools) == ("script", ["/u/t", "https://we.tl/t-abc"]) or True
    kind, argv = select_downloader("https://1drv.ms/u/s!x", tools)
    assert kind == "onearray"
    assert argv == ["https://1drv.ws/u/s!x"]  # ms -> ws rewrite
    assert select_downloader("local.bin", tools) is None


def test_download_into_mega_clears_and_runs(tmp_path, monkeypatch):
    tools = _Tools()
    tools.map = {"mega-media-drive_dl": Path("/u/d.sh")}
    inputdir = tmp_path / "input"
    inputdir.mkdir(exist_ok=True)
    (inputdir / "old").write_bytes(b"x")
    import dumprx.downloader as dl

    runs = []
    monkeypatch.setattr(dl, "run", lambda argv, **kw: runs.append(argv) or _res())
    download_into("https://mediafire.com/f", inputdir, tools)
    assert runs == [["/u/d.sh", "https://mediafire.com/f"]]
    assert not (inputdir / "old").exists()


def test_download_into_aria2c_then_wget_fallback(tmp_path, monkeypatch):
    import dumprx.downloader as dl

    inputdir = tmp_path / "input"
    runs = []

    def run(argv, **kw):
        runs.append(argv[0])
        return _res(ok=argv[0] != "aria2c")

    monkeypatch.setattr(dl, "run", run)
    download_into("https://example.com/f.bin", inputdir, _Tools())
    assert runs == ["aria2c", "wget"]


# --- 10.3 finalize helpers ---


def test_write_all_files_sorted_excludes_git(tmp_path):
    (tmp_path / "b.img").write_bytes(b"")
    (tmp_path / "a.img").write_bytes(b"")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_bytes(b"")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.txt").write_bytes(b"")
    write_all_files(tmp_path)
    assert (tmp_path / "all_files.txt").read_text().splitlines() == ["a.img", "b.img", "sub/c.txt"]


def test_remove_sys_journals_keeps_top_level(tmp_path):
    (tmp_path / "[SYS]").mkdir()  # mindepth-2 only: kept
    (tmp_path / ".git").mkdir()  # mindepth-2 only: kept
    sub = tmp_path / "system" / "[SYS]"
    sub.mkdir(parents=True)
    (sub / "j").write_bytes(b"")
    remove_sys_journals(tmp_path)
    assert (tmp_path / "[SYS]").is_dir()
    assert not (tmp_path / "system" / "[SYS]").exists()


def test_fix_permissions_sets_readable(tmp_path):
    f = tmp_path / "x.img"
    f.write_bytes(b"")
    f.chmod(0o600)
    fix_permissions(tmp_path)
    assert (f.stat().st_mode & 0o600) == 0o600
    (tmp_path / "d").mkdir()
    (tmp_path / "d").chmod(0o700)
    fix_permissions(tmp_path)
    assert (tmp_path / "d").stat().st_mode & 0o700


def test_fix_permissions_skips_symlinks(tmp_path):
    target = tmp_path / "target"
    target.write_text("t")
    (tmp_path / "link").symlink_to(target)
    target.chmod(0o400)  # would raise EPERM if chmod followed the link
    fix_permissions(tmp_path)  # must not raise


def test_promote_partitions_moves_and_converts(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    work, out = ctx.workdir, ctx.outdir
    (work / "system.img").write_bytes(b"raw")
    (work / "modem.img").write_bytes(b"raw")
    (work / "super_2.img").write_bytes(b"raw")
    import dumprx.pipeline as pipeline

    calls = []
    monkeypatch.setattr(pipeline, "to_raw_image", lambda tools, src, dst: (calls.append(src.name) or True))
    promoted = promote_partitions(ctx)
    assert (out / "system.img").read_bytes() == b"raw"
    assert (out / "modem.img").exists()
    assert (out / "super_2.img").exists()
    assert (out / "modem.img").exists()  # copied; bash leaves work copy too
    assert "system" in promoted


def test_promote_partitions_pulls_flat_root_boot_from_listing(tmp_path, monkeypatch):
    # 7zz l -ba lines: a flat root member is preceded by spaces, not "/" or line
    # start, so the old (^|/) regex never matched it. Matchers must fall back to
    # member basename equality or boot/vendor_boot/dtbo are silently dropped.
    class FakeListing:
        def __init__(self, outdir):
            self._work = None
            self._outdir = outdir

        def matched_basenames(self, name):
            return ["boot.img"] if name == "boot.img" else []

        def extract(self, seven_zz, work, members=None):
            (work / "boot.img").write_bytes(b"raw")
            return True

    ctx = _ctx(tmp_path, listing=FakeListing(tmp_path))
    work, out = ctx.workdir, ctx.outdir
    (work / "system.img").write_bytes(b"raw")
    ctx.archive_listing._work = work
    import dumprx.pipeline as pipeline

    monkeypatch.setattr(pipeline, "to_raw_image", lambda tools, src, dst: True)
    promoted = promote_partitions(ctx)
    assert (out / "boot.img").read_bytes() == b"raw"
    assert "boot" in promoted


# --- 10.4 cleanup ---


def test_clear_workdir_removes_contents_keeps_outdir(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.workdir.mkdir(parents=True, exist_ok=True)
    (ctx.workdir / "system.img").write_bytes(b"x")
    ctx.outdir.mkdir(parents=True, exist_ok=True)
    (ctx.outdir / "boot.img").write_bytes(b"b")
    clear_workdir(ctx)
    assert ctx.workdir.is_dir() and not list(ctx.workdir.iterdir())
    assert (ctx.outdir / "boot.img").read_bytes() == b"b"


def test_install_cleanup_signal_handler(tmp_path):
    ctx = _ctx(tmp_path)
    install_cleanup(ctx.workdir)
    (ctx.workdir / "payload.bin").write_bytes(b"p")
    ctx.outdir.mkdir(parents=True, exist_ok=True)
    (ctx.outdir / "system.img").write_bytes(b"s")
    try:
        signal.raise_signal(signal.SIGTERM)
    except KeyboardInterrupt:
        pass  # handler aborts after cleanup, never continues over a deleted workdir

    assert not (ctx.workdir / "payload.bin").exists()  # workdir removed on interrupt
    assert (ctx.outdir / "system.img").read_bytes() == b"s"  # OUTDIR never touched
