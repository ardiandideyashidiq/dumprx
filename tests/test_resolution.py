"""Tests for input source resolution."""

from __future__ import annotations

import pytest

from dumprx.config import build_config
from dumprx.resolution import ResolutionError, resolve_source


def test_file_source_passthrough(tmp_path):
    src = tmp_path / "firmware.zip"
    src.write_bytes(b"PK")
    res = resolve_source(src, build_config(project_dir=tmp_path, outdir=tmp_path))
    assert res.kind == "file"
    assert res.path == src.resolve()


def test_folder_single_archive_resources(tmp_path):
    d = tmp_path / "in"
    d.mkdir()
    (d / "compatibility.zip").write_bytes(b"x")  # excluded from arc discovery
    a = d / "firmware.7z"
    a.write_bytes(b"7z")
    res = resolve_source(d, build_config(project_dir=tmp_path, outdir=tmp_path))
    assert res.kind == "archive"
    assert res.path == a.resolve()


def test_folder_multi_archive_aborts(tmp_path):
    d = tmp_path / "in"
    d.mkdir()
    (d / "a.zip").write_bytes(b"")
    (d / "b.tar").write_bytes(b"")
    with pytest.raises(ResolutionError):
        resolve_source(d, build_config(project_dir=tmp_path, outdir=tmp_path))


def test_extracted_folder_copies_into_workdir(tmp_path):
    d = tmp_path / "extracted"
    d.mkdir()
    (d / "payload.bin").write_bytes(b"p")
    (d / "boot.img").write_bytes(b"b")
    cfg = build_config(project_dir=tmp_path, outdir=tmp_path)
    res = resolve_source(d, cfg)
    assert res.kind == "workdir"
    assert (cfg.paths.workdir / "payload.bin").exists()


def test_unsupported_folder(tmp_path):
    d = tmp_path / "junk"
    d.mkdir()
    (d / "notes.txt").write_text("hi")
    with pytest.raises(ResolutionError, match="not supported"):
        resolve_source(d, build_config(project_dir=tmp_path, outdir=tmp_path))
