from __future__ import annotations
import pickle
from functools import wraps
from typing import Any, Callable, TypeVar, Union
from aiogram.types import InlineKeyboardMarkup
from src.core.cache import get_redis
from loguru import logger

T = TypeVar("T", bound=Callable[..., Union[InlineKeyboardMarkup, Any]])

def cached_keyboard(ttl: int = 300):
    """
    Декоратор для кэширования inline-клавиатур в Redis.
    Поддерживает как асинхронные, так и синхронные функции.
    """
    def decorator(func: T) -> T:
        import inspect
        is_async = inspect.iscoroutinefunction(func)

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> InlineKeyboardMarkup:
            return await _get_or_set_cache(func, args, kwargs, ttl, is_async)

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> InlineKeyboardMarkup:
            # Для синхронных функций мы всё равно используем async redis, 
            # но вызываем саму функцию в зависимости от её типа.
            # В aiogram хендлеры асинхронные, поэтому обертка будет использоваться в асинхронном контексте.
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                return loop.create_task(_get_or_set_cache(func, args, kwargs, ttl, is_async))
            except RuntimeError:
                return asyncio.run(_get_or_set_cache(func, args, kwargs, ttl, is_async))

        # Возвращаем асинхронную обертку, так как она будет вызываться в хендлерах
        return async_wrapper
    return decorator

async def _get_or_set_cache(func, args, kwargs, ttl, is_async) -> InlineKeyboardMarkup:
    redis = await get_redis()
    if not redis:
        return await func(*args, **kwargs) if is_async else func(*args, **kwargs)

    # Генерация ключа
    key_parts = ["KB", func.__module__, func.__name__]
    for arg in args:
        if isinstance(arg, (int, str, bool, float)) or arg is None:
            key_parts.append(str(arg))
    for k, v in sorted(kwargs.items()):
        if isinstance(v, (int, str, bool, float)) or v is None:
            key_parts.append(f"{k}={v}")
    
    cache_key = ":".join(key_parts)

    try:
        cached_data = await redis.get(cache_key)
        if cached_data:
            return pickle.loads(cached_data)

        # Вызов оригинальной функции
        result = await func(*args, **kwargs) if is_async else func(*args, **kwargs)
        
        # Кэшируем только если это InlineKeyboardMarkup
        if isinstance(result, InlineKeyboardMarkup):
            await redis.set(cache_key, pickle.dumps(result), ex=ttl)
        return result
    except Exception as e:
        logger.warning(f"Keyboard cache error for {func.__name__}: {e}")
        return await func(*args, **kwargs) if is_async else func(*args, **kwargs)

async def invalidate_kb_cache(pattern: str = "KB:*"):
    """Очистка кэша клавиатур по паттерну."""
    redis = await get_redis()
    if not redis: return
    keys = await redis.keys(pattern)
    if keys:
        await redis.delete(*keys)
