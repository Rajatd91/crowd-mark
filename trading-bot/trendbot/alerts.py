"""Optional Telegram messages. Silent unless TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID are set; a failed alert never stops a run."""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)


def notify(text: str) -> None:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": text}, timeout=10)
    except requests.RequestException as exc:
        log.warning("telegram alert failed: %s", exc)
