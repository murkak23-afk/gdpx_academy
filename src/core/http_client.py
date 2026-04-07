from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

_session: Optional[aiohttp.ClientSession] = None
_lock = asyncio.Lock()


async def get_http_session() -> aiohttp.ClientSession:
    """Возвращает глобальную aiohttp сессию, создавая её при необходимости."""

    global _session
    if _session is None or _session.closed:
        async with _lock:
            if _session is None or _session.closed:
                timeout = aiohttp.ClientTimeout(total=30, connect=10)
                _session = aiohttp.ClientSession(timeout=timeout)
                logger.debug("Глобальная aiohttp сессия создана")
    return _session


async def close_http_session() -> None:
    """Закрывает глобальную сессию при завершении приложения."""

    global _session
    if _session is not None and not _session.closed:
        await _session.close()
        logger.debug("Глобальная aiohttp сессия закрыта")
