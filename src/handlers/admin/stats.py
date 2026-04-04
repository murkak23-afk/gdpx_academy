
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.keyboards.callbacks import (
    CB_ADMIN_DASHBOARD_RESET,
    CB_ADMIN_DASHBOARD_RESET_CONFIRM,
    CB_ADMIN_STATS_EXPORT_MONTH,
    CB_ADMIN_STATS_MONTH,
    CB_ADMIN_STATS_RESET,
    CB_ADMIN_STATS_RESET_CONFIRM,
)
from src.keyboards.constants import CALLBACK_INLINE_BACK
from src.keyboards import REPLY_BTN_BACK
from src.services import (
    AdminAuditService,
    AdminService,
    AdminStatsService,
    UserService,
)
from src.utils.text_format import edit_message_text_safe

router = Router(name="admin-stats-router")


# ── helpers ──────────────────────────────────────────────────


def _month_stats_keyboard(year: int, month: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📥 Выгрузить Excel",
                    callback_data=f"{CB_ADMIN_STATS_EXPORT_MONTH}:{year}:{month}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Обнулить статистику",
                    callback_data=CB_ADMIN_STATS_RESET,
                )
            ],
            [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)],
        ]
    )


def _month_stats_text(rows: list[dict[str, int | object]], year: int, month: int) -> str:
    lines = [
        f"📊 <b>Статистика SIM за {month:02d}.{year} (UTC)</b>",
        "",
        "<code>День | Вход | ✅ | ❌ | 🚫 | ⛔</code>",
    ]

    total_incoming = 0
    total_accepted = 0
    total_rejected = 0
    total_blocked = 0
    total_not_scan = 0

    for row in rows:
        dt = row["date"]
        day = getattr(dt, "day", 0)
        incoming = int(row["incoming"])
        accepted = int(row["accepted"])
        rejected = int(row["rejected"])
        blocked = int(row["blocked"])
        not_scan = int(row["not_a_scan"])

        total_incoming += incoming
        total_accepted += accepted
        total_rejected += rejected
        total_blocked += blocked
        total_not_scan += not_scan

        lines.append(
            f"<code>{day:02d}   | {incoming:4d} | {accepted:3d} | {rejected:3d} | {blocked:3d} | {not_scan:3d}</code>"
        )

    total_failed = total_rejected + total_blocked + total_not_scan
    lines.extend(
        [
            "",
            "<b>Итого за месяц</b>",
            f"📥 Входящих SIM: <b>{total_incoming}</b>",
            f"✅ Принято: <b>{total_accepted}</b>",
            f"❌ Брак всего: <b>{total_failed}</b> (rejected={total_rejected}, blocked={total_blocked}, not_a_scan={total_not_scan})",
        ]
    )
    return "\n".join(lines)


def _month_stats_workbook_bytes(rows: list[dict[str, int | object]], year: int, month: int) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "SIM Daily"
    ws.append(["Дата", "Входящие", "Принято", "Rejected", "Blocked", "Not a scan", "Брак всего"])

    total_incoming = 0
    total_accepted = 0
    total_rejected = 0
    total_blocked = 0
    total_not_scan = 0

    for row in rows:
        dt = row["date"]
        incoming = int(row["incoming"])
        accepted = int(row["accepted"])
        rejected = int(row["rejected"])
        blocked = int(row["blocked"])
        not_scan = int(row["not_a_scan"])
        failed_total = rejected + blocked + not_scan

        total_incoming += incoming
        total_accepted += accepted
        total_rejected += rejected
        total_blocked += blocked
        total_not_scan += not_scan

        ws.append([
            str(dt),
            incoming,
            accepted,
            rejected,
            blocked,
            not_scan,
            failed_total,
        ])

    ws.append([])
    ws.append(["ИТОГО", total_incoming, total_accepted, total_rejected, total_blocked, total_not_scan, total_rejected + total_blocked + total_not_scan])

    meta = wb.create_sheet("Summary")
    meta.append(["Период", f"{month:02d}.{year} UTC"])
    meta.append(["Входящие SIM", total_incoming])
    meta.append(["Принято", total_accepted])
    meta.append(["Rejected", total_rejected])
    meta.append(["Blocked", total_blocked])
    meta.append(["Not a scan", total_not_scan])
    meta.append(["Брак всего", total_rejected + total_blocked + total_not_scan])

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


# ── handlers ─────────────────────────────────────────────────


@router.callback_query(F.data == CB_ADMIN_STATS_MONTH)
async def on_admin_inline_stats_month(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    now = datetime.now(timezone.utc)
    year, month = now.year, now.month
    rows = await AdminStatsService(session=session).daily_sim_stats_for_month(year=year, month=month)
    text = _month_stats_text(rows, year=year, month=month)

    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            text,
            reply_markup=_month_stats_keyboard(year=year, month=month),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith(f"{CB_ADMIN_STATS_EXPORT_MONTH}:"))
async def on_admin_inline_stats_export_month(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Некорректные параметры экспорта", show_alert=True)
        return

    try:
        year = int(parts[2])
        month = int(parts[3])
    except ValueError:
        await callback.answer("Некорректный период", show_alert=True)
        return

    rows = await AdminStatsService(session=session).daily_sim_stats_for_month(year=year, month=month)
    payload = _month_stats_workbook_bytes(rows, year=year, month=month)

    await callback.answer("Формирую Excel...")
    if callback.message is not None:
        file = InputFile(BytesIO(payload), filename=f"sim_stats_{year}_{month:02d}.xlsx")
        await callback.message.answer_document(
            document=file,
            caption=f"📊 Отчёт по SIM за {month:02d}.{year}",
        )


@router.callback_query(F.data == CB_ADMIN_STATS_RESET)
async def on_admin_stats_reset_ask(callback: CallbackQuery, session: AsyncSession) -> None:
    """Запрос подтверждения обнуления статистики."""
    if callback.from_user is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            "⚠️ <b>Обнулить статистику?</b>\n\n"
            "Все счётчики в разделе «Статистика» станут 0.\n"
            "Данные в БД не удаляются — просто сдвигается точка отсчёта.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Да, обнулить",
                            callback_data=CB_ADMIN_STATS_RESET_CONFIRM,
                        ),
                        InlineKeyboardButton(
                            text="❌ Отмена",
                            callback_data=CB_ADMIN_STATS_MONTH,
                        ),
                    ]
                ]
            ),
            parse_mode="HTML",
        )


@router.callback_query(F.data == CB_ADMIN_STATS_RESET_CONFIRM)
async def on_admin_stats_reset_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    """Выполняет обнуление: сохраняет текущее время как точку отсчёта."""
    if callback.from_user is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    from src.core.stats_epoch import set_stats_epoch
    epoch = set_stats_epoch()

    await AdminAuditService(session=session).log(
        admin_id=(await UserService(session=session).get_by_telegram_id(callback.from_user.id)).id,
        action="stats_reset",
        target_type="system",
        details=f"Stats epoch set to {epoch.isoformat()}",
    )

    now = datetime.now(timezone.utc)
    year, month = now.year, now.month
    rows = await AdminStatsService(session=session).daily_sim_stats_for_month(year=year, month=month)
    text = _month_stats_text(rows, year=year, month=month)

    await callback.answer("Статистика обнулена ✅")
    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            text,
            reply_markup=_month_stats_keyboard(year=year, month=month),
            parse_mode="HTML",
        )


@router.callback_query(F.data == CB_ADMIN_DASHBOARD_RESET)
async def on_admin_dashboard_reset_ask(callback: CallbackQuery, session: AsyncSession) -> None:
    """Запрос подтверждения персонального сброса счётчиков дашборда."""
    if callback.from_user is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            "🔄 <b>Сбросить личные счётчики?</b>\n\n"
            "Счётчики «Принято всего» и «Брак всего» на твоём дашборде\n"
            "начнут считаться с нуля от текущего момента.\n\n"
            "Данные других админов не затрагиваются.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Да, обнулить",
                            callback_data=CB_ADMIN_DASHBOARD_RESET_CONFIRM,
                        ),
                        InlineKeyboardButton(
                            text="❌ Отмена",
                            callback_data=CALLBACK_INLINE_BACK,
                        ),
                    ]
                ]
            ),
            parse_mode="HTML",
        )


@router.callback_query(F.data == CB_ADMIN_DASHBOARD_RESET_CONFIRM)
async def on_admin_dashboard_reset_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    """Сохраняет персональную точку сброса, показывает обновлённый дашборд."""
    if callback.from_user is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    from src.core.personal_epoch import set_personal_epoch
    from src.utils.admin_keyboard import send_admin_dashboard
    tg_id = callback.from_user.id
    set_personal_epoch(tg_id)

    await callback.answer("Счётчики сброшены ✅")
    if callback.message is not None:
        await send_admin_dashboard(callback.message, session, tg_id)
