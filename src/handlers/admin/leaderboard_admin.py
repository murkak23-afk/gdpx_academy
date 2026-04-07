"""Admin /alead panel: toggle prize, edit prize text for the leaderboard."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.keyboards.callbacks import (
    CB_ALEAD_CANCEL_EDIT,
    CB_ALEAD_EDIT_PRIZE,
    CB_ALEAD_TOGGLE,
)
from src.keyboards.constants import CALLBACK_INLINE_BACK
from src.lexicon import Lex
from src.services import AdminService
from src.services.leaderboard_service import LeaderboardSettingsService
from src.states.leaderboard_state import LeaderboardAdminState
from src.utils.text_format import edit_message_text_safe

router = Router(name="leaderboard-admin-router")


# ── Text / keyboard builders ───────────────────────────────────────────────


def _alead_panel_text(prize_enabled: bool, prize_text: str | None) -> str:
    state_label = Lex.ALEAD_STATUS_ON if prize_enabled else Lex.ALEAD_STATUS_OFF
    text_preview = prize_text or Lex.ALEAD_NO_PRIZE_TEXT
    return (
        f"{Lex.ALEAD_HEADER}\n\n"
        f"Статус приза: <b>{state_label}</b>\n"
        f"Текст приза:\n{text_preview}\n\n"
        f"{Lex.ALEAD_HINT}"
    )


def _alead_keyboard(prize_enabled: bool) -> InlineKeyboardMarkup:
    toggle_label = Lex.BTN_PRIZE_TOGGLE_OFF if prize_enabled else Lex.BTN_PRIZE_TOGGLE_ON
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle_label, callback_data=CB_ALEAD_TOGGLE)],
            [InlineKeyboardButton(text=Lex.BTN_PRIZE_EDIT, callback_data=CB_ALEAD_EDIT_PRIZE)],
            [InlineKeyboardButton(text=Lex.BTN_BACK, callback_data=CALLBACK_INLINE_BACK)],
        ]
    )


# ── Handlers ───────────────────────────────────────────────────────────────


@router.message(Command("alead"))
async def on_alead(message: Message, session: AsyncSession) -> None:
    if message.from_user is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        return

    settings = await LeaderboardSettingsService(session=session).get()
    await message.answer(
        _alead_panel_text(settings.prize_enabled, settings.prize_text),
        reply_markup=_alead_keyboard(settings.prize_enabled),
        parse_mode="HTML",
    )


@router.callback_query(F.data == CB_ALEAD_TOGGLE)
async def on_alead_toggle(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    if callback.from_user is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer(Lex.WARN_ACCESS_DENIED_ALERT, show_alert=True)
        return

    settings_svc = LeaderboardSettingsService(session=session)
    new_state = await settings_svc.toggle_prize()
    settings = await settings_svc.get()

    state_word = "ВКЛЮЧЁН" if new_state else "ВЫКЛЮЧЕН"
    await callback.answer(Lex.ALEAD_TOGGLED.format(state=state_word))
    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            _alead_panel_text(new_state, settings.prize_text),
            reply_markup=_alead_keyboard(new_state),
            parse_mode="HTML",
        )


@router.callback_query(F.data == CB_ALEAD_EDIT_PRIZE)
async def on_alead_edit_prize_start(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if callback.from_user is None:
        return
    await state.set_state(LeaderboardAdminState.waiting_for_prize_text)
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            Lex.ALEAD_ASK_PRIZE_TEXT,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text=Lex.BTN_CANCEL, callback_data=CB_ALEAD_CANCEL_EDIT)
                ]]
            ),
        )


@router.message(
    StateFilter(LeaderboardAdminState.waiting_for_prize_text),
    F.text,
)
async def on_alead_prize_text_received(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await state.clear()
        return

    settings_svc = LeaderboardSettingsService(session=session)
    await settings_svc.set_prize_text(message.text)
    settings = await settings_svc.get()

    await state.clear()
    await message.answer(
        Lex.ALEAD_PRIZE_SAVED
        + _alead_panel_text(settings.prize_enabled, settings.prize_text),
        reply_markup=_alead_keyboard(settings.prize_enabled),
        parse_mode="HTML",
    )


@router.callback_query(
    StateFilter(LeaderboardAdminState.waiting_for_prize_text),
    F.data == CB_ALEAD_CANCEL_EDIT,
)
async def on_alead_cancel_edit(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await state.clear()
    if callback.from_user is None:
        return
    settings = await LeaderboardSettingsService(session=session).get()
    await callback.answer(Lex.OK_CANCEL)
    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            _alead_panel_text(settings.prize_enabled, settings.prize_text),
            reply_markup=_alead_keyboard(settings.prize_enabled),
            parse_mode="HTML",
        )
