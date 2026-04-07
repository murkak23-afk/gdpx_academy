from __future__ import annotations

from loguru import logger
import pickle
from contextlib import suppress
from functools import wraps
from typing import Any, Callable

from redis.asyncio import Redis

from src.core.config import get_settings


_redis: Redis | None = None


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


async def close_redis() -> None:
    """Вызывается при shutdown: закрывает соединение с Redis."""
    global _redis
    if _redis is not None:
        with suppress(Exception):
            await _redis.aclose()
        _redis = None


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
                await redis.set(cache_key, pickle.dumps(result), ex=cache_ttl)
                return result
            except Exception:
                logger.warning("Redis cache error for key=%s — falling back", cache_key, exc_info=True)
                return await func(*args, **kwargs)

        return wrapper
    return decorator
