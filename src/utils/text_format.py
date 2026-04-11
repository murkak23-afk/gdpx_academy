"""Безопасные строки для Telegram: текст сообщения не может быть пустым."""

from __future__ import annotations

import logging
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from src.utils.admin_panel_text import ADMIN_PANEL_HOME_TEXT

logger = logging.getLogger(__name__)

# Видимая заглушка для обычного текста (без parse_mode).
PLAIN_EMPTY_PLACEHOLDER = "—"

# Заглушка для сообщений с parse_mode=HTML (только если весь текст в HTML).
HTML_EMPTY_PLACEHOLDER = "<i>Без описания</i>"

# Невидимый символ (word joiner): одна «непустая» позиция для служебных сообщений (напр. только клавиатура).
PAGINATION_MESSAGE_STUB = "\u2060"


def non_empty_plain(text: str | None, *, placeholder: str = PLAIN_EMPTY_PLACEHOLDER) -> str:
    """Возвращает непустую строку после strip; иначе placeholder."""

    s = (text or "").strip()
    return s if s else placeholder


def non_empty_html(text: str | None) -> str:
    """Текст для сообщений с parse_mode=HTML: пустой ввод заменяется на курсивную заглушку."""

    s = (text or "").strip()
    return s if s else HTML_EMPTY_PLACEHOLDER


def is_message_not_modified_error(exc: BaseException) -> bool:
    """True, если Telegram вернул «message is not modified» (тот же текст/подпись)."""

    msg = str(exc).lower()
    return "message is not modified" in msg or "message_not_modified" in msg


async def edit_message_text_safe(
    message: Message,
    text: str | None,
    *,
    parse_mode: str | None = None,
    **kwargs: Any,
) -> Message | None:
    """edit_text с гарантированно непустым текстом; игнорирует «ничего не изменилось»."""

    if parse_mode == "HTML":
        safe = non_empty_html(text)
    else:
        safe = non_empty_plain(text)
    try:
        return await message.edit_text(safe, parse_mode=parse_mode, **kwargs)
    except TelegramBadRequest as exc:
        if is_message_not_modified_error(exc):
            logger.debug("edit_text: сообщение не изменилось, пропуск: %s", exc)
            return None
        raise


async def edit_message_text_or_caption_safe(
    message: Message,
    text: str | None,
    *,
    parse_mode: str | None = None,
    **kwargs: Any,
) -> Message | None:
    """Как edit_message_text_safe, но если сообщение без текста (только медиа), правит подпись."""

    if parse_mode == "HTML":
        safe = non_empty_html(text)
    else:
        safe = non_empty_plain(text)
    try:
        return await message.edit_text(safe, parse_mode=parse_mode, **kwargs)
    except TelegramBadRequest as exc:
        if is_message_not_modified_error(exc):
            logger.debug("edit_text: сообщение не изменилось, пропуск: %s", exc)
            return None
        try:
            return await message.edit_caption(caption=safe, parse_mode=parse_mode, **kwargs)
        except TelegramBadRequest as exc2:
            if is_message_not_modified_error(exc2):
                return None
            raise exc2 from exc


async def edit_message_to_admin_home(message: Message) -> Message | None:
    """Сжимает текущее сообщение в «домашний» текст админ-панели (текст или подпись к медиа)."""

    try:
        return await edit_message_text_safe(message, ADMIN_PANEL_HOME_TEXT, reply_markup=None)
    except TelegramBadRequest:
        try:
            return await message.edit_caption(caption=ADMIN_PANEL_HOME_TEXT, reply_markup=None)
        except TelegramBadRequest:
            try:
                return await message.edit_reply_markup(reply_markup=None)
            except TelegramBadRequest:
                return None


async def delete_message_safe(message: Message | None) -> None:
    """Тихое удаление сообщения с игнорированием ошибок."""
    if message is None:
        return
    try:
        await message.delete()
    except Exception:
        pass
