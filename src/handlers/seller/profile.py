"""Profile, statistics, payout history, and captcha handlers."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.keyboards import seller_main_inline_keyboard
from src.keyboards.callbacks import (
    CB_CAPTCHA_CANCEL,
    CB_CAPTCHA_START,
    CB_NOOP,
    CB_SELLER_MENU_PAYHIST,
    CB_SELLER_MENU_PROFILE,
    CB_SELLER_PAYHIST_PAGE,
    CB_SELLER_STATS_VIEW,
)
from src.services import AdminService, BillingService, SubmissionService, UserService
from src.utils.clean_screen import send_clean_text_screen
from src.utils.text_format import edit_message_text_safe
from src.utils.ui_builder import GDPXRenderer

from ._shared import (
    SELLER_PAGE_SIZE,
    _captcha_keyboard,
    _render_profile_text,
    _renderer,
    _safe_delete_message,
)

router = Router(name="seller-profile-router")


# ── Local keyboard builders ───────────────────────────────────────────────


def _stats_period_keyboard(active_period: str) -> InlineKeyboardMarkup:
    labels = [("today", "Сегодня"), ("week", "Отчёт за неделю")]
    row: list[InlineKeyboardButton] = []
    for key, label in labels:
        title = f"• {label}" if key == active_period else label
        row.append(
            InlineKeyboardButton(
                text=title, callback_data=f"{CB_SELLER_STATS_VIEW}:{key}"
            )
        )
    return InlineKeyboardMarkup(inline_keyboard=[row])


def _format_seller_stats_dashboard(user, stats: dict, *, period_label: str) -> str:
    nick = f"@{user.username}" if user.username else f"@{user.telegram_id}"
    by_op = stats["by_main_operator"]
    operator_rows = sorted(
        ((name, int(count)) for name, count in by_op.items()),
        key=lambda x: x[1],
        reverse=True,
    )
    top = [x for x in operator_rows if x[1] > 0][:3]
    lines = [
        f"Статистика продавца · {period_label}",
        "",
        "💰 Финансы",
        f"• Сумма зачёта: {stats['balance']} USDT",
        f"• Зачтено: {stats['accepted_total']} симок",
        "",
        "📊 Качество",
        f"• Блок: {stats['blocked']}",
        f"• Не скан: {stats['not_a_scan']}",
        f"• Незачёт: {stats['rejected_moderation']}",
    ]
    if top:
        lines.extend(["", "🏷 Топ операторов"])
        for name, cnt in top:
            lines.append(f"• {name}: {cnt}")
    lines.extend(["", f"Продавец: {nick}"])
    return "\n".join(lines)


def _seller_payout_history_kb(page: int, total: int) -> InlineKeyboardMarkup:
    max_page = (max(total, 1) - 1) // SELLER_PAGE_SIZE
    rows: list[list[InlineKeyboardButton]] = []
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="⬅️", callback_data=f"{CB_SELLER_PAYHIST_PAGE}:{page - 1}"
            )
        )
    nav.append(
        InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP)
    )
    if page < max_page:
        nav.append(
            InlineKeyboardButton(
                text="➡️", callback_data=f"{CB_SELLER_PAYHIST_PAGE}:{page + 1}"
            )
        )
    if nav:
        rows.append(nav)
    rows.append(
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data=CB_SELLER_MENU_PROFILE)]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_payout_history_page(
    message: Message, session: AsyncSession, *, user_id: int, page: int
) -> None:
    items, total = await BillingService(
        session=session
    ).get_user_payout_history_paginated(
        user_id=user_id,
        page=page,
        page_size=SELLER_PAGE_SIZE,
    )
    text = GDPXRenderer().render_payout_history(
        items,
        page=page,
        total=max(total, 1),
        page_size=SELLER_PAGE_SIZE,
    )
    await send_clean_text_screen(
        trigger_message=message,
        text=text,
        key="seller:payouts:history",
        reply_markup=_seller_payout_history_kb(page=page, total=total),
        parse_mode="HTML",
    )


# ── Handlers ──────────────────────────────────────────────────────────────


@router.message(Command("profile"))
@router.message(F.text.in_({"Профиль", "ПРОФИЛЬ"}))
async def on_profile(message: Message, session: AsyncSession) -> None:
    """Shows seller profile as compact dashboard."""
    if message.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer("Сначала пройди регистрацию через /start.")
        return
    dashboard = await SubmissionService(session=session).get_user_dashboard_stats(
        user_id=user.id
    )
    await message.answer(
        _render_profile_text(user, dashboard),
        reply_markup=seller_main_inline_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == CB_SELLER_MENU_PROFILE)
async def on_seller_menu_profile(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return
    dashboard = await SubmissionService(session=session).get_user_dashboard_stats(
        user_id=user.id
    )
    text = _render_profile_text(user, dashboard)
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            text,
            reply_markup=seller_main_inline_keyboard(),
            parse_mode="HTML",
        )


@router.message(Command("stats"))
@router.message(F.text == "Статистика")
async def on_stats(message: Message, session: AsyncSession) -> None:
    """Shows seller statistics dashboard."""
    if message.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer("Сначала пройди регистрацию через /start.")
        return
    stats = await SubmissionService(session=session).get_user_esim_seller_stats(
        user_id=user.id, days=1
    )
    await send_clean_text_screen(
        trigger_message=message,
        text=_format_seller_stats_dashboard(user, stats, period_label="сегодня"),
        key="seller:stats:screen",
        reply_markup=_stats_period_keyboard(active_period="today"),
    )


@router.callback_query(F.data.startswith(f"{CB_SELLER_STATS_VIEW}:"))
async def on_stats_view(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return
    period = callback.data.split(":")[3]
    days = 7 if period == "week" else 1
    period_label = "7 дней" if period == "week" else "сегодня"
    stats = await SubmissionService(session=session).get_user_esim_seller_stats(
        user_id=user.id, days=days
    )
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            _format_seller_stats_dashboard(user, stats, period_label=period_label),
            reply_markup=_stats_period_keyboard(
                active_period="week" if period == "week" else "today"
            ),
        )


@router.message(F.text == "История выплат")
async def on_payout_history_root(message: Message, session: AsyncSession) -> None:
    if message.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer("Сначала пройди регистрацию через /start.")
        return
    await _send_payout_history_page(message, session, user_id=user.id, page=0)


@router.callback_query(F.data == CB_SELLER_MENU_PAYHIST)
async def on_seller_menu_payhist(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return
    await callback.answer()
    if callback.message is not None:
        await _send_payout_history_page(callback.message, session, user_id=user.id, page=0)


@router.callback_query(F.data.startswith(f"{CB_SELLER_PAYHIST_PAGE}:"))
async def on_payout_history_page(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return
    page = max(int(callback.data.split(":")[3]), 0)
    await callback.answer()
    if callback.message is not None:
        await _send_payout_history_page(callback.message, session, user_id=user.id, page=page)


@router.callback_query(F.data == CB_CAPTCHA_CANCEL)
async def on_captcha_cancel(callback: CallbackQuery, session: AsyncSession) -> None:
    """Dismisses the inline captcha prompt and returns the main menu."""
    if callback.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    await callback.answer()
    if callback.message is not None:
        dashboard = {"accepted": 0, "pending": 0, "rejected": 0}
        if user is not None:
            dashboard = await SubmissionService(
                session=session
            ).get_user_dashboard_stats(user_id=user.id)
        text = (
            _render_profile_text(user, dashboard)
            if user is not None
            else "Сначала пройди регистрацию через /start."
        )
        await edit_message_text_safe(
            callback.message,
            text,
            reply_markup=seller_main_inline_keyboard() if user is not None else None,
            parse_mode="HTML" if user is not None else None,
        )


@router.callback_query(F.data == CB_CAPTCHA_START)
async def on_captcha_start(callback: CallbackQuery, session: AsyncSession) -> None:
    """Generates a captcha code and sends it to the user."""
    if callback.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return
    answer = await UserService(session=session).create_captcha(user.id)
    if answer is None:
        await callback.answer("Ошибка капчи", show_alert=True)
        return
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            f"Введи код ниже отдельным сообщением:\n{answer}\n\n"
            "Это упрощенная captcha для снятия ограничения.",
        )


@router.message(F.text.regexp(r"^\d{4}$"))
async def on_captcha_check(message: Message, session: AsyncSession) -> None:
    """Verifies captcha input and removes the restriction."""
    if message.from_user is None or message.text is None:
        return
    user_service = UserService(session=session)
    user = await user_service.get_by_telegram_id(message.from_user.id)
    if user is None or not user.is_restricted or not user.captcha_answer:
        return
    ok = await user_service.verify_captcha(user_id=user.id, answer=message.text.strip())
    if ok:
        dashboard = await SubmissionService(session=session).get_user_dashboard_stats(
            user_id=user.id
        )
        await message.answer(
            _render_profile_text(user, dashboard),
            reply_markup=seller_main_inline_keyboard(),
            parse_mode="HTML",
        )
        return
    await message.answer(
        "Неверный код. Нажми 'Пройти капчу' и попробуй снова.",
        reply_markup=_captcha_keyboard(),
    )


@router.message(StateFilter(None), ~F.text.startswith("/"))
async def on_seller_fallback_cleanup(message: Message, session: AsyncSession) -> None:
    """Silently deletes stray messages outside FSM for a clean chat."""
    if message.from_user is not None and await AdminService(
        session=session
    ).is_admin(message.from_user.id):
        return
    await _safe_delete_message(message)
