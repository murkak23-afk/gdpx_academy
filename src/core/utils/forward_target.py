"""Разбор chat_shared / user_shared после выбора цели через forward_target_reply_keyboard."""

from __future__ import annotations

from aiogram.types import Message

from src.presentation.common.reply import FORWARD_REQ_CHAT_CHANNEL, FORWARD_REQ_CHAT_GROUP, FORWARD_REQ_USER_DM


def target_chat_id_from_forward_pick(message: Message) -> int | None:
    """Возвращает telegram chat_id для отправки (группа/канал или user_id для ЛС)."""

    if message.chat_shared is not None:
        cs = message.chat_shared
        if cs.request_id in (FORWARD_REQ_CHAT_GROUP, FORWARD_REQ_CHAT_CHANNEL):
            return cs.chat_id
        return None
    if message.user_shared is not None:
        us = message.user_shared
        if us.request_id == FORWARD_REQ_USER_DM:
            return us.user_id
    return None
