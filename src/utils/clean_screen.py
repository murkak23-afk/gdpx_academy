from __future__ import annotations

from collections import defaultdict

from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup, Message

from src.utils.text_format import non_empty_plain

_LAST_SCREEN_BY_CHAT: dict[int, dict[str, int]] = defaultdict(dict)


async def send_clean_text_screen(
    *,
    trigger_message: Message,
    text: str,
    key: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
    """Безопасно заменяет прошлый экран бота в чате на новый."""

    chat_id = trigger_message.chat.id
    previous_id = _LAST_SCREEN_BY_CHAT[chat_id].get(key)
    if previous_id is not None:
        try:
            await trigger_message.bot.delete_message(chat_id=chat_id, message_id=previous_id)
        except TelegramAPIError:
            pass

    sent = await trigger_message.answer(non_empty_plain(text), reply_markup=reply_markup)
    _LAST_SCREEN_BY_CHAT[chat_id][key] = sent.message_id
    return sent
