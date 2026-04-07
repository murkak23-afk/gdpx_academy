"""Single-Window Screen Manager — FSM-backed "one message" UX.

Паттерн «Одного окна»: бот всегда держит ровно одно активное сообщение
на пользователя.  При переходах оно редактируется in-place; только когда
редактирование невозможно (сообщение удалено, медиа-тип не совпадает)
отправляется новое, а старое удаляется.

Ключ хранится в FSM-состоянии пользователя — не падает при перезапуске
процесса (Redis FSM).

Usage
-----
    manager = ScreenManager(state)

    # Первый показ или вынужденное пересоздание:
    await manager.show(message_or_callback, text="...", reply_markup=kb, parse_mode="HTML")

    # Обновление того же экрана (edit in-place):
    await manager.update(callback, text="...", reply_markup=new_kb)

    # Принудительно сбросить (например при выходе из FSM):
    await manager.reset(callback)
"""

from __future__ import annotations

from loguru import logger
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
)

from src.utils.text_format import (
    edit_message_text_safe,
    is_message_not_modified_error,
    non_empty_html,
    non_empty_plain,
)


_FSM_KEY = "__screen_message_id__"


class ScreenManager:
    """Manages the single "active" bot message per user conversation.

    Pass an ``FSMContext`` instance – the active message_id is persisted there
    so restarts don't lose the reference.
    """

    def __init__(self, state: FSMContext) -> None:
        self._state = state

    # ── Public API ────────────────────────────────────────────────────────

    async def show(
        self,
        source: Message | CallbackQuery,
        *,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
        parse_mode: str | None = "HTML",
        delete_trigger: bool = True,
    ) -> Message:
        """Show a screen, editing the previous message when possible.

        ``delete_trigger``: if True, the incoming user message (source) is
        deleted before sending/editing so the chat stays clean.
        """
        msg = source if isinstance(source, Message) else source.message

        # Удаляем триггер-сообщение (сообщение пользователя)
        if delete_trigger and isinstance(source, Message):
            await _delete_safe(source)

        # Попытка отредактировать существующий экран
        prev_id = await self._get_stored_id(msg)
        if prev_id is not None:
            edited = await self._try_edit(
                msg, prev_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode
            )
            if edited is not None:
                return edited

        # Старое сообщение удалено или неприменимо — шлём новое
        if prev_id is not None:
            await _delete_by_id_safe(msg, prev_id)

        safe_text = non_empty_html(text) if parse_mode == "HTML" else non_empty_plain(text)
        sent = await msg.answer(safe_text, reply_markup=reply_markup, parse_mode=parse_mode)
        await self._store_id(sent.message_id)
        return sent

    async def update(
        self,
        callback: CallbackQuery,
        *,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
        parse_mode: str | None = "HTML",
        answer_text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        """Edit the current screen in-place (callback path).

        Automatically calls ``callback.answer()``.
        """
        await callback.answer(answer_text or "", show_alert=show_alert)
        if callback.message is None:
            return
        msg = callback.message
        edited = await edit_message_text_safe(
            msg, text, parse_mode=parse_mode, reply_markup=reply_markup
        )
        if edited is not None:
            await self._store_id(edited.message_id)

    async def reset(self, source: Message | CallbackQuery) -> None:
        """Delete the tracked message and clear the FSM key."""
        msg = source if isinstance(source, Message) else source.message
        if msg is None:
            return
        prev_id = await self._get_stored_id(msg)
        if prev_id is not None:
            await _delete_by_id_safe(msg, prev_id)
        await self._clear_id()

    # ── Internal ──────────────────────────────────────────────────────────

    async def _get_stored_id(self, msg: Message | None) -> int | None:
        data = await self._state.get_data()
        raw = data.get(_FSM_KEY)
        return int(raw) if raw is not None else None

    async def _store_id(self, message_id: int) -> None:
        await self._state.update_data(**{_FSM_KEY: message_id})

    async def _clear_id(self) -> None:
        data = await self._state.get_data()
        data.pop(_FSM_KEY, None)
        await self._state.set_data(data)

    async def _try_edit(
        self,
        msg: Message,
        message_id: int,
        *,
        text: str,
        reply_markup: InlineKeyboardMarkup | None,
        parse_mode: str | None,
    ) -> Message | None:
        """Try editing message_id in the same chat. Returns edited message or None."""
        safe_text = non_empty_html(text) if parse_mode == "HTML" else non_empty_plain(text)
        try:
            if msg.bot is None:
                return None
            return await msg.bot.edit_message_text(
                chat_id=msg.chat.id,
                message_id=message_id,
                text=safe_text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        except TelegramBadRequest as exc:
            if is_message_not_modified_error(exc):
                # сообщение не изменилось — считаем успехом, возвращаем ссылку на исходное
                return msg
            # Сообщение удалено, chat не найден и др. — нужно создать заново
            logger.debug("ScreenManager: edit failed (%s), will resend", exc)
            return None


# ── Module-level helpers ──────────────────────────────────────────────────


async def _delete_safe(msg: Message) -> None:
    try:
        await msg.delete()
    except TelegramBadRequest:
        pass


async def _delete_by_id_safe(ctx_msg: Message, message_id: int) -> None:
    try:
        if ctx_msg.bot is not None:
            await ctx_msg.bot.delete_message(
                chat_id=ctx_msg.chat.id, message_id=message_id
            )
    except TelegramBadRequest:
        pass
