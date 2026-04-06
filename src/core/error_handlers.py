
"""Глобальная обработка ошибок апдейтов: классификация и логирование."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram import Dispatcher
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError, TelegramRetryAfter
from aiogram.types import ErrorEvent
from sqlalchemy.exc import SQLAlchemyError

if TYPE_CHECKING:
    from aiogram import Bot

logger = logging.getLogger(__name__)


def _user_id_from_update(event: ErrorEvent) -> int | None:
    u = event.update
    if u.message and u.message.from_user:
        return u.message.from_user.id
    if u.edited_message and u.edited_message.from_user:
        return u.edited_message.from_user.id
    if u.callback_query and u.callback_query.from_user:
        return u.callback_query.from_user.id
    if u.inline_query and u.inline_query.from_user:
        return u.inline_query.from_user.id
    if u.chosen_inline_result and u.chosen_inline_result.from_user:
        return u.chosen_inline_result.from_user.id
    if u.shipping_query and u.shipping_query.from_user:
        return u.shipping_query.from_user.id
    if u.pre_checkout_query:
        return u.pre_checkout_query.from_user.id
    if u.poll_answer and u.poll_answer.user:
        return u.poll_answer.user.id
    if u.my_chat_member and u.my_chat_member.from_user:
        return u.my_chat_member.from_user.id
    if u.chat_member and u.chat_member.from_user:
        return u.chat_member.from_user.id
    if u.chat_join_request and u.chat_join_request.from_user:
        return u.chat_join_request.from_user.id
    return None


async def _maybe_notify_admin_critical(
    *,
    bot: Bot | None,
    exc: BaseException,
    update_id: int | None,
    user_id: int | None,
) -> None:
    """Шлёт алерты в чат (временный хардкод для теста)."""
    if bot is None:
        return

    # ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←
    chat_id = -1003859937194  # ←←← СЮДА ВСТАВЬ РЕАЛЬНЫЙ ID ТВОЕЙ ГРУППЫ
    # ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←

    from html import escape
    import traceback
    from datetime import datetime

    error_type = type(exc).__name__
    error_msg = escape(str(exc))

    tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__, limit=5))
    tb_escaped = escape(tb_str)

    text = (
        f"🚨 <b>#КРИТИЧЕСКА_ОШИБКА</b> {datetime.utcnow():%Y-%m-%d %H:%M:%S} UTC\n\n"
        f"<b>Тип:</b> {error_type}\n"
        f"<b>Update ID:</b> <code>{update_id}</code>\n"
        f"<b>User ID:</b> <code>{user_id}</code>\n\n"
        f"<b>Сообщение:</b>\n<pre>{error_msg[:500]}</pre>\n\n"
        f"<b>Traceback:</b>\n<pre><code class='language-python'>{tb_escaped[:2000]}</code></pre>"
    )

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        logger.info(f"✅ Алерт отправлен в чат {chat_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки в чат {chat_id}: {e}", exc_info=True)


def register_error_handlers(dispatcher: Dispatcher) -> None:
    """Регистрирует обработчик @dispatcher.errors() с разделением ожидаемых API-ошибок и багов."""

    @dispatcher.errors()
    async def on_error(event: ErrorEvent, bot: Bot | None = None) -> None:
        exc = event.exception
        update_id = event.update.update_id
        user_id = _user_id_from_update(event)
        ctx_extra = f" update_id={update_id} user_id={user_id}"

        if isinstance(exc, TelegramRetryAfter):
            logger.warning(
                "Telegram flood control%s: %s (retry_after=%s)",
                ctx_extra,
                exc,
                getattr(exc, "retry_after", "?"),
            )
            return

        if isinstance(exc, TelegramNetworkError):
            logger.warning("Telegram network error%s: %s", ctx_extra, exc)
            return

        if isinstance(exc, TelegramAPIError):
            logger.warning("Telegram API error%s: %s", ctx_extra, exc)
            return

        if isinstance(exc, SQLAlchemyError):
            logger.error("Ошибка БД%s: %s", ctx_extra, exc, exc_info=True)
            await _maybe_notify_admin_critical(
                bot=bot,
                exc=exc,
                update_id=update_id,
                user_id=user_id,
            )
            return

        logger.error("Необработанное исключение%s: %s", ctx_extra, exc, exc_info=True)
        await _maybe_notify_admin_critical(
            bot=bot,
            exc=exc,
            update_id=update_id,
            user_id=user_id,
        )
