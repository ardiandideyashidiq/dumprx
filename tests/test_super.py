"""Tests for shared super.img handling (extractors/super.py)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dumprx.config import build_config
from dumprx.extractors import WorkContext, classify, load_extractors


@pytest.fixture(autouse=True)
def _registered():
    load_extractors()


class _FakeTools:
    """Tool resolver that only sees stub binaries created by the test."""

    def __init__(self, utilsdir: Path):
        self.utilsdir = Path(utilsdir)

    def __getitem__(self, name: str):
        from dumprx.tools import TOOL_MAP

        segment = TOOL_MAP.get(name, name)
        p = self.utilsdir / segment
        return p if p.is_file() else None

    @property
    def seven_zz(self) -> str:
        return "7zz"


def _stub(utils_dir: Path, name: str) -> None:
    p = utils_dir / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# stub\n")


def _ctx(tmp_path, name="bundle.zip", listing=None, monkeypatch=None) -> WorkContext:
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
    ctx = WorkContext(
        source=src,
        outdir=paths.outdir,
        workdir=paths.workdir,
        config=cfg,
        archive_listing=listing,
    )
    if monkeypatch is not None:
        monkeypatch.setattr(
            WorkContext,
            "tools",
            property(lambda self: _FakeTools(self.config.paths.utilsdir)),
        )
    return ctx


def _res(ok=True, code=0):
    return SimpleNamespace(ok=ok, returncode=code, stdout=b"", stderr=b"", elapsed_ms=0)


def test_lpunpack_loop_renames_a_to_plain(tmp_path, monkeypatch):
    import dumprx.extractors.super as sm

    _stub(tmp_path / "utils", "lpunpack")
    ctx = _ctx(tmp_path, monkeypatch=monkeypatch)
    work = ctx.workdir
    (work / "super.img.raw").write_bytes(b"raw")
    calls: list = []

    def run(argv, **kw):
        calls.append(argv)
        if "--partition=system_a" in argv[1]:
            (work / "system_a.img").write_bytes(b"p")
        if "--partition=product_a" in argv[1]:
            (work / "product_a.img").write_bytes(b"p")
        return _res()

    monkeypatch.setattr(sm, "run", run)
    sm.lpunpack_partitions(ctx, work / "super.img.raw")

    joins = " ".join(" ".join(c) for c in calls)
    assert "--partition=system_a" in joins and "--partition=product_a" in joins
    assert (work / "system.img").exists() and (work / "system_a.img").exists() is False
    assert (work / "product.img").exists() and (work / "product_a.img").exists() is False


def test_lpunpack_falls_back_to_plain_partition(tmp_path, monkeypatch):
    import dumprx.extractors.super as sm

    _stub(tmp_path / "utils", "lpunpack")
    ctx = _ctx(tmp_path, monkeypatch=monkeypatch)
    work = ctx.workdir
    (work / "super.img.raw").write_bytes(b"raw")
    calls: list = []

    def run(argv, **kw):
        calls.append(argv)
        if "--partition=system_a" in argv[1]:
            return _res(ok=False, code=2)
        if "--partition=system " in argv[1] or argv[1] == "--partition=system":
            (work / "system.img").write_bytes(b"p")
        return _res()

    monkeypatch.setattr(sm, "run", run)
    sm.lpunpack_partitions(ctx, work / "super.img.raw")
    joins = [" ".join(c) for c in calls]
    assert joins.index(next(j for j in joins if "--partition=system_a" in j)) < joins.index(
        next(j for j in joins if "--partition=system " in j)
    )
    assert (work / "system.img").exists()


def test_superimage_extract_full_flow(tmp_path, monkeypatch):
    import dumprx.extractors.super as sm

    _stub(tmp_path / "utils", "lpunpack")
    ctx = _ctx(tmp_path, monkeypatch=monkeypatch)
    work = ctx.workdir
    (work / "super.img").write_bytes(b"raw")
    calls: list = []

    def fake_run(argv, **kw):
        calls.append(argv)
        part = argv[1].split("=", 1)[1]
        (work / f"{part}.img").write_bytes(b"p")
        return _res()

    monkeypatch.setattr(sm, "to_raw_image", lambda tools, src, dst: (dst.write_bytes(b"r") or True))
    monkeypatch.setattr(sm, "run", fake_run)
    sm.superimage_extract(ctx)
    assert any("--partition=system_a" in " ".join(c) for c in calls)
    assert (work / "system.img").exists()
    assert not (work / "super.img").exists()
    assert not (work / "super.img.raw").exists()


def test_superimage_extract_merges_duplicate_extra(tmp_path, monkeypatch):
    import dumprx.extractors.super as sm

    _stub(tmp_path / "utils", "lpunpack")
    ctx = _ctx(tmp_path, monkeypatch=monkeypatch)
    work = ctx.workdir
    (work / "super.img").write_bytes(b"raw")
    extra = work / "sub" / "super.img"
    extra.parent.mkdir()
    extra.write_bytes(b"raw2")
    merged: list = []

    def fake_merge(tools, super_file, extra_file):
        merged.append((super_file, extra_file))
        (work / "super.img.raw").write_bytes(b"m")
        return True

    def fake_run(argv, **kw):
        part = argv[1].split("=", 1)[1]
        (work / f"{part}.img").write_bytes(b"p")
        return _res()

    monkeypatch.setattr(sm, "super_to_raw", fake_merge)
    monkeypatch.setattr(sm, "run", fake_run)
    sm.superimage_extract(ctx, extras=[extra])
    assert merged and merged[0] == (work / "super.img", extra)
    assert (work / "system.img").exists()


def test_superimage_extract_ignores_missing_super(tmp_path, monkeypatch):
    import dumprx.extractors.super as sm

    ctx = _ctx(tmp_path, monkeypatch=monkeypatch)
    calls: list = []
    monkeypatch.setattr(sm, "run", lambda argv, **kw: calls.append(argv) or _res())
    sm.superimage_extract(ctx)
    assert calls == []


def test_aml_container_uses_shared_super(tmp_path, monkeypatch):
    import dumprx.extractors.containers as containers
    import dumprx.extractors.super as sm

    _stub(tmp_path / "utils", "lpunpack")
    _stub(tmp_path / "utils", "aml-upgrade-package-extract")
    ctx = _ctx(
        tmp_path,
        "update.aml.zip",
        listing=SimpleNamespace(member_names=["update_aml.img"]),
        monkeypatch=monkeypatch,
    )
    work = ctx.workdir
    calls: list = []

    def fake_container_run(argv, **kw):
        calls.append(argv)
        if "7zz" in argv[0]:
            (work / "update_aml.img").write_bytes(b"u")
        if "aml-upgrade" in str(argv[0]):
            (work / "super.img").write_bytes(b"s")
            (work / "system.img").write_bytes(b"s")
        return _res()

    def fake_super_run(argv, **kw):
        calls.append(argv)
        part = argv[1].split("=", 1)[1]
        (work / f"{part}.img").write_bytes(b"p")
        return _res()

    monkeypatch.setattr(containers, "run", fake_container_run)
    monkeypatch.setattr(sm, "to_raw_image", lambda tools, src, dst: (dst.write_bytes(b"r") or True))
    monkeypatch.setattr(sm, "run", fake_super_run)
    assert classify(ctx).name == "aml"
    classify(ctx).extract(ctx)
    assert (work / "super.img").is_file() is False
    assert any("--partition=" in " ".join(c) for c in calls)
