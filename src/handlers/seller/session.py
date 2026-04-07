"""Panic button: session termination — purge chat history + FSM state reset.

Flow
----
1. User presses "⊗ ЗАВЕРШИТЬ СЕССИЮ" in the profile keyboard.
   → on_session_terminate: edit current message to confirmation screen.
2. User presses "◾ ПОДТВЕРДИТЬ ОЧИСТКУ".
   → on_session_terminate_confirm:
       a. answer() the callback immediately (remove spinner).
       b. Concurrently delete up to _DELETE_WINDOW messages backwards from
          the current message_id (fail-open per message — TelegramBadRequest
          for unknown IDs is expected and suppressed).
       c. state.clear() — wipes all FSM data from Redis.
       d. Send single final monospace message.
"""

from __future__ import annotations

import asyncio
from loguru import logger

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from src.keyboards.callbacks import (
    CB_SELLER_MENU_PROFILE,
    CB_SESSION_TERMINATE,
    CB_SESSION_TERMINATE_CONFIRM,
)
from src.lexicon import Lex

router = Router(name="seller-session-router")

# How many messages backwards to attempt deletion.
# Telegram only allows deleting messages < 48 hours old; unknown IDs are silently skipped.
_DELETE_WINDOW = 50


def _terminate_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=Lex.BTN_TERMINATE_CONFIRM,
                    callback_data=CB_SESSION_TERMINATE_CONFIRM,
                ),
            ],
            [
                InlineKeyboardButton(
                    text=Lex.BTN_CANCEL,
                    callback_data=CB_SELLER_MENU_PROFILE,
                ),
            ],
        ]
    )


@router.callback_query(F.data == CB_SESSION_TERMINATE)
async def on_session_terminate(callback: CallbackQuery) -> None:
    """Show confirmation screen before wiping the session."""
    await callback.answer()
    if callback.message is None:
        return
    from src.utils.text_format import edit_message_text_or_caption_safe
    try:
        await edit_message_text_or_caption_safe(
            callback.message,
            text=Lex.INFO_SESSION_TERMINATE_CONFIRM,
            reply_markup=_terminate_confirm_keyboard(),
            parse_mode="HTML",
        )
    except TelegramAPIError:
        pass


@router.callback_query(F.data == CB_SESSION_TERMINATE_CONFIRM)
async def on_session_terminate_confirm(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Execute: bulk-delete messages, clear FSM, send terminal message."""
    await callback.answer("[ ИНИЦИАЛИЗАЦИЯ ОЧИСТКИ... ]", show_alert=False)

    if callback.message is None or callback.bot is None:
        return

    chat_id = callback.message.chat.id
    bot = callback.bot
    current_msg_id = callback.message.message_id

    # Build delete coroutines for the current message + _DELETE_WINDOW prior ones.
    async def _try_delete(msg_id: int) -> None:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass  # Expected for messages outside 48h window, already deleted, etc.

    delete_tasks = [
        _try_delete(mid)
        for mid in range(current_msg_id, max(current_msg_id - _DELETE_WINDOW - 1, 0), -1)
    ]
    await asyncio.gather(*delete_tasks)

    # Full FSM reset — clears state + all stored data keys.
    await state.clear()

    # Final tombstone message (no keyboard, plain monospace).
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=Lex.INFO_SESSION_TERMINATED,
            parse_mode="HTML",
        )
    except Exception:
        logger.debug("Не удалось отправить завершающее сообщение сессии в чат %s", chat_id)
