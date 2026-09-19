"""Telegram notification: failure tolerated, never aborts a dump."""

from __future__ import annotations

from loguru import logger

from dumprx.config import Config
from dumprx.process import run


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


__all__ = ["send_tg_html"]
