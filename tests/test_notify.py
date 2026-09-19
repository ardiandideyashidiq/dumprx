"""Group 14: notify.py verbosity gating + failure-tolerant send contract."""

from __future__ import annotations

from dumprx.config import Config, Paths, Secrets, Settings
from dumprx.notify import esc, send_tg_alert, send_tg_event


def _cfg(tmp_path, verbosity="normal", tg_token="tok"):
    return Config(
        paths=Paths(tmp_path, tmp_path / "input", tmp_path / "utils"),
        settings=Settings(tg_verbosity=verbosity),
        secrets=Secrets(tg_token=tg_token),
    )


def test_event_gated_below_threshold(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(
        "dumprx.notify.send_tg_html", lambda text, config: sent.append(text) or True
    )
    cfg = _cfg(tmp_path, verbosity="minimal")
    assert send_tg_event(cfg, "milestone", min_level="normal") is False
    assert sent == []


def test_event_sent_at_normal_and_verbose(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(
        "dumprx.notify.send_tg_html", lambda text, config: sent.append(text) or True
    )
    for verbosity in ("normal", "verbose"):
        sent.clear()
        assert send_tg_event(_cfg(tmp_path, verbosity=verbosity), "milestone") is True
        assert sent == ["milestone"]


def test_alert_bypasses_gating(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(
        "dumprx.notify.send_tg_html", lambda text, config: sent.append(text) or True
    )
    assert send_tg_alert(_cfg(tmp_path, verbosity="minimal"), "boom") is True
    assert sent == ["boom"]


def test_tokenless_event_never_reaches_transport(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(
        "dumprx.notify.send_tg_html", lambda text, config: called.append(text) or True
    )
    assert send_tg_event(_cfg(tmp_path, tg_token=""), "milestone") is False
    assert called == []  # gating rejects before reaching the transport


def test_tokenless_alert_hits_real_transport_guard(tmp_path):
    assert send_tg_alert(_cfg(tmp_path, tg_token=""), "boom") is False  # no network


def test_send_failure_tolerated(monkeypatch, tmp_path):
    monkeypatch.setattr("dumprx.notify.send_tg_html", lambda text, config: False)
    assert send_tg_event(_cfg(tmp_path), "milestone") is False  # no raise, False result


def test_esc_escapes_special_characters():
    assert esc('A & B <C> > D "quote"') == 'A &amp; B &lt;C&gt; &gt; D "quote"'
