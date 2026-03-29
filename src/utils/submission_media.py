"""Отправка материала в Telegram: фото или документ (архив)."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Document, Message

from src.database.models.submission import Submission

logger = logging.getLogger(__name__)

ATTACHMENT_PHOTO = "photo"
ATTACHMENT_DOCUMENT = "document"

_ARCHIVE_SUFFIXES = (
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".tgz",
    ".bz2",
    ".xz",
    ".zst",
    ".lz",
    ".lzma",
    ".cab",
    ".arj",
)

_ARCHIVE_MIME_KEYWORDS = (
    "zip",
    "rar",
    "7z",
    "tar",
    "gzip",
    "x-gzip",
    "bzip",
    "xz",
    "compress",
    "archive",
    "octet-stream",
)


def is_allowed_archive_document(document: Document) -> bool:
    """Проверяет, что документ похож на архив (расширение или MIME)."""

    name = (document.file_name or "").lower()
    if any(name.endswith(suf) for suf in _ARCHIVE_SUFFIXES):
        return True
    mt = (document.mime_type or "").lower()
    if not mt:
        return False
    return any(k in mt for k in _ARCHIVE_MIME_KEYWORDS)


def caption_trim(text: str | None, limit: int = 1024) -> str | None:
    """Подпись к медиа: пустая строка/пробелы → не отправляем caption (None)."""

    if text is None:
        return None
    s = text.strip()
    if not s:
        return None
    return s[:limit] if len(s) > limit else s


async def _send_document(
    bot: Bot,
    chat_id: int,
    file_id: str,
    caption: str | None,
    **kwargs: Any,
) -> Any:
    return await bot.send_document(
        chat_id=chat_id,
        document=file_id,
        caption=caption,
        **kwargs,
    )


async def _send_photo(
    bot: Bot,
    chat_id: int,
    file_id: str,
    caption: str | None,
    **kwargs: Any,
) -> Any:
    return await bot.send_photo(
        chat_id=chat_id,
        photo=file_id,
        caption=caption,
        **kwargs,
    )


async def bot_send_submission(
    bot: Bot,
    chat_id: int,
    submission: Submission,
    caption: str | None,
    **kwargs: Any,
) -> Any:
    """Отправляет в чат фото или документ; при ошибке типа пробует второй вариант."""

    cap = caption_trim(caption)
    preferred_document = submission.attachment_type == ATTACHMENT_DOCUMENT

    first_try = _send_document if preferred_document else _send_photo
    second_try = _send_photo if preferred_document else _send_document

    try:
        return await first_try(bot, chat_id, submission.telegram_file_id, cap, **kwargs)
    except TelegramAPIError as first_exc:
        logger.warning(
            "Telegram API: первичная отправка не удалась (submission_id=%s chat_id=%s type=%s): %s",
            submission.id,
            chat_id,
            submission.attachment_type,
            first_exc,
        )
        try:
            result = await second_try(bot, chat_id, submission.telegram_file_id, cap, **kwargs)
            logger.info(
                "Telegram API: fallback-отправка успешна (submission_id=%s chat_id=%s)",
                submission.id,
                chat_id,
            )
            return result
        except TelegramAPIError as second_exc:
            logger.warning(
                "Telegram API: fallback тоже не удался (submission_id=%s chat_id=%s): %s",
                submission.id,
                chat_id,
                second_exc,
            )
            raise


async def message_answer_submission(
    message: Message,
    submission: Submission,
    caption: str,
    **kwargs: Any,
) -> Any:
    """Отвечает сообщением с фото или документом."""

    cap = caption_trim(caption)
    try:
        if submission.attachment_type == ATTACHMENT_DOCUMENT:
            return await message.answer_document(
                document=submission.telegram_file_id,
                caption=cap,
                **kwargs,
            )
        return await message.answer_photo(
            photo=submission.telegram_file_id,
            caption=cap,
            **kwargs,
        )
    except TelegramAPIError as exc:
        logger.warning(
            "Telegram API: не удалось ответить с submission_id=%s: %s",
            submission.id,
            exc,
        )
        raise
