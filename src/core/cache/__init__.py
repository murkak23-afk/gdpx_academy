from __future__ import annotations

import pickle
from contextlib import suppress
from functools import wraps
from typing import Any, Callable

from loguru import logger
from redis.asyncio import Redis
from arq.connections import ArqRedis, create_pool, RedisSettings

from src.core.config import get_settings

_redis: Redis | None = None
_arq_pool: ArqRedis | None = None


async def invalidate_cache_pattern(pattern: str):
    """Удаляет ключи по паттерну."""
    redis = await get_redis()
    if not redis: return
    keys = await redis.keys(pattern)
    if keys:
        await redis.delete(*keys)


async def get_redis() -> Redis | None:
    """Ленивая инициализация Redis-клиента.

    Возвращает None (без исключения), если REDIS_URL не задан —
    кэш просто не работает, бот продолжает работать без него.
    """
    global _redis
    if _redis is not None:
        return _redis
    settings = get_settings()
    if not settings.redis_url:
        return None
    _redis = Redis.from_url(
        settings.redis_url,
        decode_responses=False,  # храним pickle/bytes
        socket_timeout=5,
        socket_connect_timeout=5,
    )
    return _redis


async def get_arq_pool() -> ArqRedis | None:
    """Ленивая инициализация пула ARQ."""
    global _arq_pool
    if _arq_pool is not None:
        return _arq_pool
    settings = get_settings()
    if not settings.redis_url:
        return None
    
    # Парсим URL для arq RedisSettings
    _redis_url = settings.redis_url
    if _redis_url.startswith("redis://"):
        _redis_url = _redis_url[8:]
        host_port = _redis_url.split("@")[-1].split("/")[0]
        host, port = host_port.split(":") if ":" in host_port else (host_port, 6379)
    else:
        host, port = 'localhost', 6379
        
    _arq_pool = await create_pool(RedisSettings(host=host, port=int(port)))
    return _arq_pool


async def close_redis() -> None:
    """Вызывается при shutdown: закрывает соединение с Redis."""
    global _redis, _arq_pool
    if _redis is not None:
        with suppress(Exception):
            await _redis.aclose()
        _redis = None
    if _arq_pool is not None:
        with suppress(Exception):
            await _arq_pool.close()
        _arq_pool = None


def cached(ttl: int | Callable[[], int] | None = None, key_prefix: str = "") -> Callable:
    """Декоратор кэширования в Redis (pickle).

    ttl — секунды жизни записи. Принимает int, callable() → int, или None
          (тогда 300 с). Callable позволяет читать TTL из config лениво,
          чтобы не вызывать get_settings() на этапе импорта.

    Ключ строится из: prefix + имя функции + аргументы (кроме self/cls).
    При недоступном Redis — прозрачный fallback к реальному вызову.
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Вычисляем TTL (может быть lambda из сервиса)
            if callable(ttl):
                cache_ttl = ttl()
            else:
                cache_ttl = ttl if ttl is not None else 300

            redis = await get_redis()
            if redis is None:
                # Redis не сконфигурирован — работаем без кэша
                return await func(*args, **kwargs)

            # Ключ: пропускаем args[0] если это объект с _session (service instance)
            key_args = args[1:] if args and hasattr(args[0], "_session") else args
            parts = [key_prefix or func.__qualname__]
            parts.extend(str(a) for a in key_args)
            parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            cache_key = ":".join(parts)

            try:
                cached_data = await redis.get(cache_key)
                if cached_data:
                    return pickle.loads(cached_data)  # noqa: S301

                result = await func(*args, **kwargs)
                if result is not None:
                    await redis.set(cache_key, pickle.dumps(result), ex=cache_ttl)
                return result
            except Exception:
                logger.warning("Redis cache error for key={} — falling back", cache_key)
                return await func(*args, **kwargs)

        return wrapper
    return decorator


class UserCache:
    """Хелпер для быстрого кэширования базовых данных пользователя."""
    
    PREFIX = "u_data"

    @classmethod
    async def get_status(cls, user_id: int) -> dict | None:
        """Получает статус блокировки и роль из кэша."""
        redis = await get_redis()
        if not redis: return None
        data = await redis.get(f"{cls.PREFIX}:{user_id}:status")
        if data:
            return pickle.loads(data)
        return None

    @classmethod
    async def set_status(cls, user_id: int, is_restricted: bool, is_active: bool, role: str, ttl: int = 45):
        """Сохраняет статус пользователя в кэше."""
        redis = await get_redis()
        if not redis: return
        payload = {"is_restricted": is_restricted, "is_active": is_active, "role": role}
        await redis.set(f"{cls.PREFIX}:{user_id}:status", pickle.dumps(payload), ex=ttl)

    @classmethod
    async def invalidate(cls, user_id: int):
        """Инвалидирует кэш при изменении данных администратором."""
        redis = await get_redis()
        if not redis: return
        await redis.delete(f"{cls.PREFIX}:{user_id}:status")
