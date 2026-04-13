from __future__ import annotations

import logging
import pickle
from typing import TYPE_CHECKING
from aiogram import F, Router
from aiogram.types import CallbackQuery

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import Message

from src.core.cache import get_redis
from src.presentation.common.factory import NotificationCD

logger = logging.getLogger(__name__)
router = Router(name="notifications-router")


@router.callback_query(NotificationCD.filter(F.action == "close"))
async def close_notification(callback: CallbackQuery) -> None:
    """Удаляет сообщение уведомления и очищает данные в Redis."""
    try:
        await clear_notifications(callback.from_user.id, callback.bot, callback.message)
        await callback.answer("Уведомление закрыто")
    except Exception as e:
        logger.error(f"Error closing notification: {e}")
        try:
            await callback.message.delete()
        except:
            pass


async def clear_notifications(user_tg_id: int, bot: "Bot", message: "Message" = None) -> None:
    """Очищает уведомления для пользователя."""
    redis = await get_redis()
    if not redis:
        if message:
            await message.delete()
        return

    uid = await redis.get(f"tgid_to_uid:{user_tg_id}")
    if not uid:
        if message:
            await message.delete()
        return

    cache_key = f"notif_v4:{uid}"
    raw = await redis.get(cache_key)
    if raw:
        data = pickle.loads(raw)
        msg_id = data.get("msg_id")
        if msg_id:
            try:
                await bot.delete_message(user_tg_id, msg_id)
            except Exception:
                pass
        await redis.delete(cache_key)
    elif message:
        await message.delete()
