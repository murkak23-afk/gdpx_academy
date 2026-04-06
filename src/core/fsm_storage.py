"""Выбор FSM-хранилища: Redis для продакшена / нескольких воркеров, Memory для локальной разработки."""

from __future__ import annotations

import logging

from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from src.core.config import get_settings

logger = logging.getLogger(__name__)


def build_fsm_storage() -> BaseStorage:
    """Возвращает RedisStorage при заданном REDIS_URL, иначе MemoryStorage с предупреждением в лог."""

    settings = get_settings()
    if settings.redis_url:
        storage = RedisStorage.from_url(
            settings.redis_url,
            state_ttl=3600,  # 1 час
            data_ttl=3600
        )
        logger.info("FSM: используется RedisStorage (REDIS_URL задан, TTL 1 час)")
        return storage

    logger.warning("Используется MemoryStorage. Не для продакшена!")
    return MemoryStorage()


