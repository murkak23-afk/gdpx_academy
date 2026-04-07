"""Admin User Management — Agent Dossier.

FSM flow
────────
Entry:
  CB_ADMIN_USER_SEARCH              → on_admin_user_search_start
      set waiting_for_tg_id, prompt for Telegram ID

  waiting_for_tg_id (text)          → on_admin_user_tg_id_input
      look up user → show dossier + action buttons

Dossier action buttons (callback_data carries target tg_id):
  CB_ADMIN_USER_OPEN:{tg_id}        → on_admin_user_open    (refresh dossier)
  CB_ADMIN_USER_BAN:{tg_id}         → on_admin_user_ban     (toggle is_active)
  CB_ADMIN_USER_BALANCE:{tg_id}     → on_admin_user_balance_start
      set waiting_for_balance_delta
  CB_ADMIN_USER_DM:{tg_id}          → on_admin_user_dm_start
      set waiting_for_dm_text

  waiting_for_balance_delta (text)  → on_admin_user_balance_input
      parse +/-N.NN, update pending_balance, write audit log

  waiting_for_dm_text (text)        → on_admin_user_dm_send
      bot.send_message(target_tg_id, text), write audit log
"""

from __future__ import annotations

import re
from loguru import logger
from decimal import Decimal, InvalidOperation

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from src.keyboards import REPLY_BTN_BACK
from src.keyboards.callback_data import AdminUserBalanceCB, AdminUserBanCB, AdminUserDmCB, AdminUserOpenCB
from src.keyboards.callbacks import CB_ADMIN_USER_SEARCH
from src.keyboards.constants import CALLBACK_INLINE_BACK
from src.services import AdminAuditService, AdminService, UserService
from src.states.admin_state import AdminUserMgmtState
from src.utils.audit_logger import log_admin_action
from src.utils.formatters import get_rank_info
from src.utils.text_format import edit_message_text_safe

router = Router(name="admin-users-router")

# ── FSM data keys ─────────────────────────────────────────────────────────
_KEY_TARGET_TG_ID = "user_mgmt_target_tg_id"

# +15.5 or -5 or +0.50
_DELTA_RE = re.compile(r"^([+-])(\d+(?:\.\d{1,2})?)$")

DIVIDER = "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰"


# ── Keyboards ─────────────────────────────────────────────────────────────


def _search_prompt_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)
    return b.as_markup()


def _dossier_keyboard(tg_id: int, is_active: bool) -> InlineKeyboardMarkup:
    ban_label = "🔴 ЗАБАНИТЬ" if is_active else "🟢 РАЗБАНИТЬ"
    b = InlineKeyboardBuilder()
    b.button(text="💸 ИЗМЕНИТЬ СУММУ К ВЫПЛАТЕ", callback_data=AdminUserBalanceCB(tg_id=tg_id))
    b.button(text=ban_label, callback_data=AdminUserBanCB(tg_id=tg_id))
    b.button(text="✉ ЛИЧНОЕ СООБЩЕНИЕ", callback_data=AdminUserDmCB(tg_id=tg_id))
    b.button(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)
    b.adjust(1, 2, 1)
    return b.as_markup()


def _cancel_keyboard(tg_id: int) -> InlineKeyboardMarkup:
    """Back → dossier of the target user."""
    b = InlineKeyboardBuilder()
    b.button(text="◀ К ДОСЬЕ", callback_data=AdminUserOpenCB(tg_id=tg_id))
    return b.as_markup()


# ── Text builder ──────────────────────────────────────────────────────────


def _render_dossier(user) -> str:  # type: ignore[type-arg]
    username = f"@{user.username}" if user.username else "—"
    rank_label, _ = get_rank_info(user.total_paid)
    status = "🟢 ACTIVE" if user.is_active else "🔴 BANNED"
    return (
        f"❖ <b>DOSSIER // SELLER: <code>{username}</code></b>\n"
        f"{DIVIDER}\n"
        f"┕ ID: <code>{user.telegram_id}</code>\n"
        f"┕ РАНГ: <code>{rank_label}</code>\n"
        f"┕ К ВЫПЛАТЕ: <code>{user.pending_balance:.2f}</code> USDT\n"
        f"┕ ВЫПЛАЧЕНО ВСЕГО: <code>{user.total_paid:.2f}</code> USDT\n"
        f"┕ СТАТУС: <code>{status}</code>"
    )


# ── Entry point ───────────────────────────────────────────────────────────


@router.callback_query(F.data == CB_ADMIN_USER_SEARCH)
async def on_admin_user_search_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("НЕДОСТАТОЧНО ПРАВ", show_alert=True)
        return
    await state.set_state(AdminUserMgmtState.waiting_for_tg_id)
    await callback.answer()
    await edit_message_text_safe(
        callback.message,
        "🔍 <b>ПОИСК СЕЛЛЕРА</b>\n\n ОТПРАВЬ TELEGRAM ID ПОЛЬЗОВАТЕЛЯ (ЧИСЛОВОЙ):",
        reply_markup=_search_prompt_keyboard(),
        parse_mode="HTML",
    )


# ── Refresh dossier via callback ──────────────────────────────────────────


@router.callback_query(AdminUserOpenCB.filter())
async def on_admin_user_open(
    callback: CallbackQuery,
    callback_data: AdminUserOpenCB,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("НЕДОСТАТОЧНО ПРАВ", show_alert=True)
        return
    tg_id = callback_data.tg_id
    user = await UserService(session=session).get_by_telegram_id(tg_id)
    if user is None:
        await callback.answer("СЕЛЛЕР НЕ НАЙДЕН", show_alert=True)
        return
    await callback.answer()
    await edit_message_text_safe(
        callback.message,
        _render_dossier(user),
        reply_markup=_dossier_keyboard(tg_id, user.is_active),
        parse_mode="HTML",
    )


# ── Step 1 of search: receive TG ID text ─────────────────────────────────


@router.message(AdminUserMgmtState.waiting_for_tg_id)
async def on_admin_user_tg_id_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await state.clear()
        return

    raw = message.text.strip()
    if not raw.lstrip("-").isdigit():
        await message.answer(
            "TELEGRAM ID - ЭТО ЧИСЛО. ПОПРОБУЙ ЕЩЁ РАЗ:",
            reply_markup=_search_prompt_keyboard(),
        )
        return

    tg_id = int(raw)
    user = await UserService(session=session).get_by_telegram_id(tg_id)
    if user is None:
        await message.answer(
            f"СЕЛЛЕР С TG ID <code>{tg_id}</code> НЕ НАЙДЕН В БАЗЕ.\n"
            "ПРОВЕРЬ ID И ОТПРАВЬ СНОВА.",
            reply_markup=_search_prompt_keyboard(),
            parse_mode="HTML",
        )
        return

    await state.clear()
    await message.answer(
        _render_dossier(user),
        reply_markup=_dossier_keyboard(tg_id, user.is_active),
        parse_mode="HTML",
    )


# ── Ban / unban ───────────────────────────────────────────────────────────


@router.callback_query(AdminUserBanCB.filter())
async def on_admin_user_ban(
    callback: CallbackQuery,
    callback_data: AdminUserBanCB,
    session: AsyncSession,
) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("НЕДОСТАТОЧНО ПРАВ", show_alert=True)
        return
    tg_id = callback_data.tg_id

    user = await UserService(session=session).get_by_telegram_id(tg_id)
    if user is None:
        await callback.answer("СЕЛЛЕР НЕ НАЙДЕН", show_alert=True)
        return

    new_status = not user.is_active
    user.is_active = new_status
    action = "user_unbanned" if new_status else "user_banned"

    await AdminAuditService(session=session).log(
        admin_id=(await UserService(session=session).get_by_telegram_id(callback.from_user.id)).id,  # type: ignore[union-attr]
        action=action,
        target_type="user",
        target_id=user.id,
        details=f"tg_id={tg_id}",
    )
    log_admin_action(
        admin_id=callback.from_user.id,
        action=action,
        target_tg_id=tg_id,
        new_is_active=new_status,
    )

    label = "РАЗБАНЕН" if new_status else "ЗАБАНЕН"
    await callback.answer(f"✅ СЕЛЛЕР {label}", show_alert=False)
    await edit_message_text_safe(
        callback.message,
        _render_dossier(user),
        reply_markup=_dossier_keyboard(tg_id, user.is_active),
        parse_mode="HTML",
    )


# ── Balance: start ────────────────────────────────────────────────────────


@router.callback_query(AdminUserBalanceCB.filter())
async def on_admin_user_balance_start(
    callback: CallbackQuery,
    callback_data: AdminUserBalanceCB,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("НЕДОСТАТОЧНО ПРАВ", show_alert=True)
        return
    tg_id = callback_data.tg_id
    user = await UserService(session=session).get_by_telegram_id(tg_id)
    if user is None:
        await callback.answer("СЕЛЛЕР НЕ НАЙДЕН", show_alert=True)
        return

    await state.set_state(AdminUserMgmtState.waiting_for_balance_delta)
    await state.update_data(**{_KEY_TARGET_TG_ID: tg_id})
    await callback.answer()
    await edit_message_text_safe(
        callback.message,
        (
            f"💰 <b>ИЗМЕНИТЬ СУММУ К ВЫПЛАТЕ</b>\n\n"
            f"СЕЛЛЕР: <code>{user.telegram_id}</code>\n"
            f"ТЕКУЩАЯ СУММА К ВЫПЛАТЕ: <code>{user.pending_balance:.2f}</code> USDT\n"
            f"ВСЕГО ВЫПЛАЧЕНО: <code>{user.total_paid:.2f}</code> USDT\n\n"
            f"ВВЕДИ СУММУ: <code>+15.50</code> (ДОБАВИТЬ) ИЛИ <code>-5.00</code> (ВЫЧЕСТЬ):"
        ),
        reply_markup=_cancel_keyboard(tg_id),
        parse_mode="HTML",
    )


# ── Balance: apply ────────────────────────────────────────────────────────


@router.message(AdminUserMgmtState.waiting_for_balance_delta)
async def on_admin_user_balance_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    tg_id: int | None = data.get(_KEY_TARGET_TG_ID)
    if tg_id is None:
        await state.clear()
        await message.answer("ОШИБКА СЕССИИ. НАЧНИ ПОИСК ЗАНОВО.")
        return

    raw = (message.text or "").strip()
    m = _DELTA_RE.match(raw)
    if not m:
        await message.answer(
            "ФОРМАТ: <code>+15.50</code> ИЛИ <code>-5.00</code>\nОБЯЗАТЕЛЬНО УКАЗЫВАЙ ЗНАК + ИЛИ −.",
            parse_mode="HTML",
            reply_markup=_cancel_keyboard(tg_id),
        )
        return

    sign, amount_str = m.group(1), m.group(2)
    try:
        delta = Decimal(amount_str)
    except InvalidOperation:
        await message.answer("НЕКОРРЕКТНОЕ ЧИСЛО. ПОПРОБУЙ ЕЩЁ РАЗ.", reply_markup=_cancel_keyboard(tg_id))
        return
    if sign == "-":
        delta = -delta

    user = await UserService(session=session).get_by_telegram_id(tg_id)
    if user is None:
        await state.clear()
        await message.answer("СЕЛЛЕР НЕ НАЙДЕН.")
        return

    old_balance = user.pending_balance
    user.pending_balance = Decimal(user.pending_balance) + delta
    if user.pending_balance < Decimal("0"):
        user.pending_balance = Decimal("0")

    admin_user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if admin_user is not None:
        await AdminAuditService(session=session).log(
            admin_id=admin_user.id,
            action="balance_adjusted",
            target_type="user",
            target_id=user.id,
            details=f"tg_id={tg_id};old={old_balance};delta={delta:+};new={user.pending_balance}",
        )
    log_admin_action(
        admin_id=message.from_user.id,
        action="balance_adjusted",
        target_tg_id=tg_id,
        old_balance=str(old_balance),
        delta=f"{delta:+}",
        new_balance=str(user.pending_balance),
    )

    await state.clear()
    await message.answer(
        (
            f"✅ <b>СУММА К ВЫПЛАТЕ ОБНОВЛЕНА</b>\n\n"
            f"СЕЛЛЕР: <code>{tg_id}</code>\n"
            f"БЫЛО: <code>{old_balance:.2f}</code> → СТАЛО: <code>{user.pending_balance:.2f}</code> USDT"
        ),
        reply_markup=_dossier_keyboard(tg_id, user.is_active),
        parse_mode="HTML",
    )


# ── DM: start ─────────────────────────────────────────────────────────────


@router.callback_query(AdminUserDmCB.filter())
async def on_admin_user_dm_start(
    callback: CallbackQuery,
    callback_data: AdminUserDmCB,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("НЕДОСТАТОЧНО ПРАВ", show_alert=True)
        return
    tg_id = callback_data.tg_id
    user = await UserService(session=session).get_by_telegram_id(tg_id)
    if user is None:
        await callback.answer("СЕЛЛЕР НЕ НАЙДЕН", show_alert=True)
        return

    await state.set_state(AdminUserMgmtState.waiting_for_dm_text)
    await state.update_data(**{_KEY_TARGET_TG_ID: tg_id})
    await callback.answer()
    await edit_message_text_safe(
        callback.message,
        (
            f"✉ <b>ЛИЧНОЕ СООБЩЕНИЕ</b>\n\n"
            f"Получатель: <code>{tg_id}</code>\n\n"
            f"Введи текст сообщения:"
        ),
        reply_markup=_cancel_keyboard(tg_id),
        parse_mode="HTML",
    )


# ── DM: send ──────────────────────────────────────────────────────────────


@router.message(AdminUserMgmtState.waiting_for_dm_text)
async def on_admin_user_dm_send(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    tg_id: int | None = data.get(_KEY_TARGET_TG_ID)
    if tg_id is None:
        await state.clear()
        await message.answer("ОШИБКА СЕССИИ.")
        return

    text = message.text.strip()
    if not text:
        await message.answer("ТЕКСТ НЕ МОЖЕТ БЫТЬ ПУСТЫМ. ПОПРОБУЙ ЕЩЁ РАЗ.")
        return

    await state.clear()

    try:
        await bot.send_message(chat_id=tg_id, text=text)
    except Exception as exc:
        logger.warning("DM to tg_id=%s failed: %s", tg_id, exc)
        await message.answer(
            f"⚠️ НЕ УДАЛОСЬ ОТПРАВИТЬ СООБЩЕНИЕ СЕЛЛЕРУ <code>{tg_id}</code>.\n"
            f"ПРИЧИНА: {exc}",
            parse_mode="HTML",
        )
        return

    admin_user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if admin_user is not None:
        await AdminAuditService(session=session).log(
            admin_id=admin_user.id,
            action="admin_dm_sent",
            target_type="user_tg_id",
            target_id=tg_id,
            details=f"len={len(text)}",
        )
    log_admin_action(
        admin_id=message.from_user.id,
        action="admin_dm_sent",
        target_tg_id=tg_id,
        msg_len=len(text),
    )

    user = await UserService(session=session).get_by_telegram_id(tg_id)
    await message.answer(
        f"✅ СООБЩЕНИЕ ДОСТАВЛЕНО СЕЛЛЕРУ <code>{tg_id}</code>.",
        reply_markup=_dossier_keyboard(tg_id, user.is_active if user else True),
        parse_mode="HTML",
    )
