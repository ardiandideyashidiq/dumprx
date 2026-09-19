"""Group: redundancy.py unit tests + CLI bail/record behavior."""

from __future__ import annotations

import hashlib
import json

from dumprx import cli
from dumprx import redundancy as red


def _fake_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(red, "_ledger_path", lambda: tmp_path / "ledger.json")
    return tmp_path / "ledger.json"


def test_sha256_stream_matches_hashlib(tmp_path):
    data = b"firmware-bytes" * 1000
    path = tmp_path / "f.bin"
    path.write_bytes(data)
    assert red.sha256_stream(path) == hashlib.sha256(data).hexdigest()


def test_sha256_stream_missing_file_returns_empty(tmp_path):
    assert red.sha256_stream(tmp_path / "missing.bin") == ""


def test_lookup_missing_ledger_empty(tmp_path, monkeypatch):
    _fake_ledger(tmp_path, monkeypatch)
    assert red.lookup("deadbeef") is None


def test_record_lookup_roundtrip(tmp_path, monkeypatch):
    ledger = _fake_ledger(tmp_path, monkeypatch)
    out = tmp_path / "out"
    out.mkdir(parents=True)
    (out / "all_files.txt").write_text("a.txt\n", encoding="utf-8")

    class _Info:
        manufacturer = "itel"
        codename = "P661N"
        branch = "b"

    red.record("digest1", outdir=out, mode="local", info=_Info())
    entry = red.lookup("digest1")
    assert entry is not None
    assert entry["identity"]["manufacturer"] == "itel"
    assert entry["identity"]["codename"] == "P661N"
    assert json.loads(ledger.read_text(encoding="utf-8"))["digest1"]["mode"] == "local"


def test_lookup_stale_when_outdir_deleted(tmp_path, monkeypatch):
    _fake_ledger(tmp_path, monkeypatch)
    out = tmp_path / "out"
    out.mkdir(parents=True)
    red.record("digest1", outdir=out, mode="local", info=type("I", (), {})())
    assert red.lookup("digest1") is None  # outdir gone -> stale -> re-dump allowed


def test_record_empty_digest_is_noop(tmp_path, monkeypatch):
    ledger = _fake_ledger(tmp_path, monkeypatch)
    red.record("", outdir=tmp_path, mode="local", info=type("I", (), {})())
    assert not ledger.exists()


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


def _setup(monkeypatch, tmp_path):
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
                "secrets": type("Sec", (), {"tg_token": "tok", "tg_chat": ""}),
            },
        )()

    monkeypatch.setattr(cli, "build_config", fake_config)
    monkeypatch.setattr(cli, "bootstrap", lambda *a, **k: None)
    monkeypatch.setattr(cli, "setup_complete", lambda: True)

    from dumprx.pipeline import PipelineResult

    monkeypatch.setattr(
        cli,
        "run_pipeline",
        lambda ctx: PipelineResult(outdir=out, terminal="", partitions=["system"]),
    )
    monkeypatch.setattr(cli, "init_repo", lambda out, br, fallback_branch="": br)
    monkeypatch.setattr(cli, "commit_local", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_make_info", lambda config: _Info())
    monkeypatch.setattr(
        cli, "write_readme", lambda o, info: (o.mkdir(parents=True, exist_ok=True), o / "README.md")[1]
    )
    monkeypatch.setattr(cli, "generate_twrp", lambda *a, **k: None)
    _fake_ledger(tmp_path, monkeypatch)
    return out


def test_main_bails_before_pipeline_on_same_file(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    fir = tmp_path / "firmware.zip"
    fir.write_bytes(b"the-same-firmware")
    calls: list[str] = []

    def fake_pipeline(ctx):
        from dumprx.pipeline import PipelineResult

        calls.append("pipeline")
        return PipelineResult(outdir=ctx.outdir, terminal="", partitions=["system"])

    monkeypatch.setattr(cli, "run_pipeline", fake_pipeline)
    out = tmp_path / "out"

    assert cli.main(["-m", "local", str(fir), "--no-setup"]) == 0
    assert calls == ["pipeline"]
    (out / "all_files.txt").write_text("x\n", encoding="utf-8")

    assert cli.main(["-m", "local", str(fir), "--no-setup"]) == 0
    assert calls == ["pipeline"]  # second run bailed, no re-extraction


def test_main_force_overrides_redundancy(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    fir = tmp_path / "firmware.zip"
    fir.write_bytes(b"the-same-firmware")
    calls: list[str] = []

    def fake_pipeline(ctx):
        from dumprx.pipeline import PipelineResult

        calls.append("pipeline")
        return PipelineResult(outdir=ctx.outdir, terminal="", partitions=["system"])

    monkeypatch.setattr(cli, "run_pipeline", fake_pipeline)
    out = tmp_path / "out"
    cli.main(["-m", "local", str(fir), "--no-setup"])
    (out / "all_files.txt").write_text("x\n", encoding="utf-8")

    assert cli.main(["-m", "local", str(fir), "--no-setup", "--force"]) == 0
    assert calls == ["pipeline", "pipeline"]  # forced re-dump ran again


def test_main_records_after_local_success(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    fir = tmp_path / "firmware.zip"
    data = b"brand-new-firmware"
    fir.write_bytes(data)
    assert cli.main(["-m", "local", str(fir), "--no-setup"]) == 0
    (tmp_path / "out" / "all_files.txt").write_text("x\n", encoding="utf-8")

    digest = hashlib.sha256(data).hexdigest()
    entry = red.lookup(digest)
    assert entry is not None
    assert entry["identity"]["codename"] == "a"
