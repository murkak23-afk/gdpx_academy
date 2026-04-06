"""Опциональные алерты в Telegram (служебный чат), с ограничением частоты."""

from __future__ import annotations

import asyncio
import logging
import time
from html import escape

import aiohttp

from src.core.config import get_settings
from src.core.http_client import get_http_session

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
_last_sent_monotonic: dict[str, float] = {}


async def _send_telegram_html(chat_id: int, text: str) -> None:
    settings = get_settings()
    url = f"https://api.telegram.org/bot{settings.bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    
    session = await get_http_session()
    async with session.post(url, json=payload) as resp:
        if resp.status != 200:
            body = await resp.text()
            logger.warning("Alert send failed: HTTP %s %s", resp.status, body[:500])


async def alert_cryptobot_error(detail: str, *, dedupe_key: str = "cryptobot_api") -> None:
    """Шлёт сообщение в ALERT_TELEGRAM_CHAT_ID не чаще, чем раз в cooldown (см. конфиг)."""

    settings = get_settings()
    chat_id = settings.alert_telegram_chat_id
    if chat_id is None:
        return

    cooldown = settings.alert_cryptobot_cooldown_sec
    now = time.monotonic()
    async with _lock:
        last = _last_sent_monotonic.get(dedupe_key, 0.0)
        if now - last < cooldown:
            return
        _last_sent_monotonic[dedupe_key] = now

    safe = escape(detail.strip())[:3500]
    text = f"<b>CryptoBot / Crypto Pay</b>\nОшибка API при операции (создание чека и т.п.).\n<pre>{safe}</pre>"
    try:
        await _send_telegram_html(chat_id, text)
    except Exception:
        logger.exception("Не удалось отправить алерт CryptoBot в Telegram")
