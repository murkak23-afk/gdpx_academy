
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
    notification_service: NotificationService | None,
    exc: BaseException,
    update_id: int | None,
    user_id: int | None,
) -> None:
    """Шлёт алерты в чат администраторов через NotificationService. (ОТКЛЮЧЕНО ПО ПРОСЬБЕ ПОЛЬЗОВАТЕЛЯ)"""
    # if notification_service is None:
    #     logger.warning("NotificationService не найден в диспетчере.")
    #     return

    # await notification_service.notify_critical_error(
    #     exc=exc,
    #     update_id=update_id,
    #     user_id=user_id
    # )
    pass


def register_error_handlers(dispatcher: Dispatcher) -> None:
    """Регистрирует обработчик @dispatcher.errors() с разделением ожидаемых API-ошибок и багов."""

    @dispatcher.errors()
    async def on_error(event: ErrorEvent, notification_service: NotificationService | None = None) -> None:
        exc = event.exception
        update_id = event.update.update_id
        user_id = _user_id_from_update(event)

        # 1. Специфические ошибки Telegram (не баги кода)
        if isinstance(exc, TelegramRetryAfter):
            logger.warning(f"Flood limit: засыпаем на {exc.retry_after}с (user {user_id})")
            return
        if isinstance(exc, (TelegramNetworkError, TelegramAPIError)):
            logger.error(f"Telegram API Error: {exc} (user {user_id})")
            return

        # 2. Ошибки БД
        if isinstance(exc, SQLAlchemyError):
            logger.critical(f"Database Error: {exc} (user {user_id})", exc_info=True)
            await _maybe_notify_admin_critical(
                notification_service=notification_service,
                exc=exc,
                update_id=update_id,
                user_id=user_id,
            )
            return

        # 3. Непредвиденные исключения (реальные баги)
        logger.exception(f"Unhandled Exception: {exc} (user {user_id})")
        await _maybe_notify_admin_critical(
            notification_service=notification_service,
            exc=exc,
            update_id=update_id,
            user_id=user_id,
        )
