"""Admin Global Analytics Dashboard — Stage 11.

Handler
───────
CB_ADMIN_ANALYTICS → on_admin_analytics
    Assembles five financial/operational metrics via AnalyticsService
    (five concurrent SQL queries) and renders a formatted SYNDICATE EYE
    report.  Accessible to any confirmed admin; does NOT expose internal
    write operations.

Report format:
    ❖ SYNDICATE EYE // GLOBAL REPORT
    ─────────────────────────────────
    ┕ ОБЩИЙ ОБОРОТ: 12 450.00 USDT
    ┕ ОБОРОТ 24Ч: 320.00 USDT
    ┕ ВЫДАНО eSIM: 8 431 шт. (успешных)
    ┕ ОТКЛОНЕНО eSIM: 1 204 шт.
    ┕ ДОЛГ ПЕРЕД АГЕНТАМИ: 890.50 USDT
    ─────────────────────────────────
    ⌄ Сводка сформирована: 01.06.2026 14:30 UTC
"""

from __future__ import annotations

from loguru import logger

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.keyboards import REPLY_BTN_BACK
from src.keyboards.callbacks import CB_ADMIN_ANALYTICS
from src.keyboards.constants import CALLBACK_INLINE_BACK
from src.services import AdminService
from src.services.analytics_service import AnalyticsReport, AnalyticsService
from src.utils.text_format import edit_message_text_safe

router = Router(name="admin-analytics-router")

DIVIDER = "─" * 36


# ── Keyboard ───────────────────────────────────────────────────────────────


def _analytics_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 ОБНОВИТЬ", callback_data=CB_ADMIN_ANALYTICS)],
            [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)],
        ]
    )


# ── Report renderer ────────────────────────────────────────────────────────


def _render_report(report: AnalyticsReport) -> str:
    ts = report.generated_at.strftime("%d.%m.%Y %H:%M UTC")
    return (
        f"❖ <b>SYNDICATE EYE // GLOBAL REPORT</b>\n"
        f"{DIVIDER}\n"
        f"┕ ОБЩИЙ ОБОРОТ: <code>{report.total_turnover:,.2f} USDT</code>\n"
        f"┕ ОБОРОТ 24Ч: <code>{report.turnover_24h:,.2f} USDT</code>\n"
        f"┕ ВЫДАНО eSIM: <code>{report.esim_accepted:,} шт.</code> (успешных)\n"
        f"┕ ОТКЛОНЕНО eSIM: <code>{report.esim_rejected:,} шт.</code>\n"
        f"┕ ДОЛГ ПЕРЕД АГЕНТАМИ: <code>{report.pending_payouts_sum:,.2f} USDT</code>\n"
        f"{DIVIDER}\n"
        f"⌄ Сводка сформирована: <i>{ts}</i>"
    )


# ── Handler ────────────────────────────────────────────────────────────────


@router.callback_query(F.data == CB_ADMIN_ANALYTICS)
async def on_admin_analytics(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    if callback.from_user is None or callback.message is None:
        return

    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("НЕДОСТАТОЧНО ПРАВ", show_alert=True)
        return

    await callback.answer()

    # Spinner while queries run
    await edit_message_text_safe(
        callback.message,
        "📊 <b>SYNDICATE EYE</b>\n\n⏳ Формирование отчёта…",
        parse_mode="HTML",
    )

    try:
        report = await AnalyticsService(session=session).get_global_report()
    except Exception as exc:
        logger.exception("Analytics report failed: %s", exc)
        await edit_message_text_safe(
            callback.message,
            "⚠️ Ошибка при формировании отчёта. Повторите попытку.",
            reply_markup=_analytics_keyboard(),
        )
        return

    await edit_message_text_safe(
        callback.message,
        _render_report(report),
        reply_markup=_analytics_keyboard(),
        parse_mode="HTML",
    )
