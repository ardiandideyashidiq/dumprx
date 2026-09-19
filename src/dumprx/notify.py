"""Telegram notification: failure tolerated, never aborts a dump."""

from __future__ import annotations

from html import escape

from loguru import logger

from dumprx.config import Config
from dumprx.process import run

_LEVELS = {"minimal": 0, "normal": 1, "verbose": 2}


def _verbosity_at_least(config: Config, min_level: str) -> bool:
    if not config.secrets.tg_token:
        return False
    return _LEVELS.get(config.settings.tg_verbosity, 1) >= _LEVELS.get(min_level, 1)


def send_tg_html(text: str, config: Config) -> bool:
    """POST the HTML card to Telegram. Returns False on any failure."""
    token = config.secrets.tg_token
    chat_id = config.secrets.tg_chat or "@DumprXDumps"
    if not token:
        logger.info("TG_TOKEN/TG_CHAT unset; skipping telegram")
        return False
    from urllib.parse import quote

    payload = (
        f"text={quote(text)}&chat_id={quote(str(chat_id))}"
        "&parse_mode=HTML&disable_web_page_preview=True"
    )
    result = run(
        [
            "curl",
            "-s",
            f"https://api.telegram.org/bot{token}/sendmessage",
            "--data",
            payload,
        ],
        timeout=60,
    )
    if not result.ok:
        logger.warning("telegram notification error (rc={})", result.returncode)
        return False
    return True


def send_tg_event(config: Config, text: str, *, min_level: str = "normal") -> bool:
    """Send a verbosity-gated milestone message; skipped when below threshold."""
    if not _verbosity_at_least(config, min_level):
        return False
    return send_tg_html(text, config)


def send_tg_alert(config: Config, text: str) -> bool:
    """Send a failure alert; never gated by verbosity."""
    return send_tg_html(text, config)


def esc(value: object) -> str:
    """HTML-escape a value interpolated into a Telegram HTML message."""
    return escape(str(value), quote=False)


__all__ = ["esc", "send_tg_alert", "send_tg_event", "send_tg_html"]
