from __future__ import annotations

import asyncio
import csv
import hashlib
import re
from datetime import datetime, timezone
from io import StringIO

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Document,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.database.models.enums import SubmissionStatus
from src.database.models.submission import Submission
from src.keyboards import (
    is_sell_esim_button,
    seller_main_inline_keyboard,
)
from src.keyboards.callbacks import (
    CB_CAPTCHA_CANCEL,
    CB_CAPTCHA_START,
    CB_NOOP,
    CB_SELLER_CANCEL_FSM,
    CB_SELLER_BATCH_CSV_NO,
    CB_SELLER_BATCH_CSV_YES,
    CB_SELLER_BATCH_REJECT,
    CB_SELLER_BATCH_SEND,
    CB_SELLER_FINISH_BATCH,
    CB_SELLER_FSM_CAT,
    CB_SELLER_INFO_FAQ,
    CB_SELLER_INFO_MANUALS,
    CB_SELLER_INFO_ROOT,
    CB_SELLER_MANUAL_OPEN,
    CB_SELLER_MAT_BACK,
    CB_SELLER_MAT_CAT,
    CB_SELLER_MAT_DELETE,
    CB_SELLER_MAT_DELETE_CONFIRM,
    CB_SELLER_MAT_EDIT,
    CB_SELLER_MAT_EDIT_MEDIA,
    CB_SELLER_MAT_FILTER,
    CB_SELLER_MAT_ITEM,
    CB_SELLER_MAT_PAGE,
    CB_SELLER_MENU_INFO,
    CB_SELLER_MENU_MATERIAL,
    CB_SELLER_MENU_PAYHIST,
    CB_SELLER_MENU_PROFILE,
    CB_SELLER_MENU_QUICK_ADD,
    CB_SELLER_MENU_SELL,
    CB_SELLER_MENU_SUPPORT,
    CB_SELLER_PAYHIST_PAGE,
    CB_SELLER_STATS_VIEW,
)
from src.main_operators import MAIN_OPERATOR_GROUPS
from src.services import (
    AdminService,
    BillingService,
    CategoryService,
    SellerQuotaService,
    SubmissionService,
    UserService,
)
from src.states.submission_state import SubmissionState
from src.utils.clean_screen import send_clean_text_screen
from src.utils.fsm_progress import FSMProgressFormatter
from src.utils.phone_norm import PHONE_NORM_ERROR_HTML, normalize_phone_strict
from src.utils.submission_media import (
    ATTACHMENT_DOCUMENT,
    ATTACHMENT_PHOTO,
    bot_send_submission,
    is_allowed_archive_document,
)
from src.manuals import MANUALS, get_manual_by_id
from src.utils.text_format import edit_message_text_safe
from src.utils.ui_builder import GDPXRenderer

router = Router(name="seller-router")
SELLER_PAGE_SIZE = 5
DEFAULT_INFO_CHAT_URL = "https://t.me/+cFWhTnl_iew1ZjZi"
MATERIAL_FILTER_ALL = "all"
MATERIAL_FILTER_ACTIVE = "active"
MATERIAL_FILTER_CREDIT = "credit"
MATERIAL_FILTER_DEBIT = "debit"
MATERIAL_FILTER_ORDER = (
    MATERIAL_FILTER_ALL,
    MATERIAL_FILTER_ACTIVE,
    MATERIAL_FILTER_CREDIT,
    MATERIAL_FILTER_DEBIT,
)
_renderer = GDPXRenderer()
_batch_idle_tasks: dict[int, asyncio.Task] = {}

# ---------- Мануалы ----------


def _manuals_list_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура со списком всех мануалов."""
    rows: list[list[InlineKeyboardButton]] = []
    for m in MANUALS:
        rows.append([
            InlineKeyboardButton(
                text=f"{m.emoji} {m.title}",
                callback_data=f"{CB_SELLER_MANUAL_OPEN}:{m.id}",
            )
        ])
    rows.append([InlineKeyboardButton(text="⬅️ В INFO", callback_data=CB_SELLER_INFO_ROOT)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _manual_detail_keyboard() -> InlineKeyboardMarkup:
    """Кнопка назад к списку мануалов."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К мануалам", callback_data=CB_SELLER_INFO_MANUALS)],
    ])


SELLER_DELETABLE_STATUSES = {
    SubmissionStatus.PENDING,
    SubmissionStatus.REJECTED,
    SubmissionStatus.BLOCKED,
    SubmissionStatus.NOT_A_SCAN,
}

REJECT_NO_NUMBER = "no_number"
REJECT_BAD_FILE = "bad_file"
REJECT_DUPLICATE_BATCH = "duplicate_batch"
REJECT_NUMBER_WITHOUT_MEDIA = "number_without_media"

REJECT_LABELS: dict[str, str] = {
    REJECT_NO_NUMBER: "без номера",
    REJECT_BAD_FILE: "неподдерживаемый файл",
    REJECT_DUPLICATE_BATCH: "дубликат в батче",
    REJECT_NUMBER_WITHOUT_MEDIA: "номер без фото/файла",
}


def _format_seller_esim_stats(user, stats: dict) -> str:
    """Текст раздела «Статистика» для продавца eSIM."""

    nick = f"@{user.username}" if user.username else f"@{user.telegram_id}"
    lines = [
        "Статистика eSIM",
        "",
        f"Продавец: {nick} | user_id: {user.telegram_id}",
        "",
        f"Всего засчитано eSIM: {stats['accepted_total']}",
        f"Общий заработок: {stats['balance']} USDT",
        "",
        f"Блоков: {stats['blocked']}",
        f"Не скан / не подходит: {stats['not_a_scan']}",
        f"Отклонено модерацией: {stats['rejected_moderation']}",
        "",
        "Засчитано eSIM по основным операторам:",
    ]
    by_op = stats["by_main_operator"]
    for label, _ in MAIN_OPERATOR_GROUPS:
        lines.append(f"  • {label}: {by_op[label]}")
    lines.append(f"  • Прочие операторы: {by_op['Другое']}")
    return "\n".join(lines)


def _format_seller_profile(user, dashboard: dict, esim_stats: dict) -> str:
    """Компактный современный экран профиля продавца."""

    nickname = f"@{user.username}" if user.username else f"@{user.telegram_id}"
    if user.is_restricted:
        account_status = "ограничен"
    elif user.duplicate_timeout_until is not None:
        account_status = f"таймаут до {user.duplicate_timeout_until:%Y-%m-%d %H:%M UTC}"
    else:
        account_status = "активен"

    by_operator = esim_stats.get("by_main_operator", {})
    top_rows: list[tuple[str, int]] = sorted(
        ((str(name), int(count)) for name, count in by_operator.items()),
        key=lambda x: x[1],
        reverse=True,
    )
    top_rows = [row for row in top_rows if row[1] > 0][:3]

    lines = [
        "Профиль продавца",
        "",
        "👤 Аккаунт",
        f"• Ник: {nickname}",
        f"• ID: {user.telegram_id}",
        f"• Статус: {account_status}",
        "",
        "💰 Финансы",
        f"• К выплате: {user.pending_balance} USDT",
        f"• Засчитано: {dashboard['accepted']} симок",
        f"• Всего заработано: {dashboard['balance']} USDT",
        "",
        "📊 Симки",
        f"• В очереди / в работе: {dashboard['pending']}",
        f"• Зачёт: {dashboard['accepted']}",
        f"• Незачёт: {dashboard['rejected']}",
    ]
    if top_rows:
        lines.extend(["", "🏷 Топ операторы по зачёту"])
        for name, count in top_rows:
            lines.append(f"• {name}: {count}")
    return "\n".join(lines)


def _stats_period_keyboard(active_period: str) -> InlineKeyboardMarkup:
    labels = [("today", "Сегодня"), ("week", "Отчёт за неделю")]
    row: list[InlineKeyboardButton] = []
    for key, label in labels:
        title = f"• {label}" if key == active_period else label
        row.append(InlineKeyboardButton(text=title, callback_data=f"{CB_SELLER_STATS_VIEW}:{key}"))
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


def _info_root_keyboard(channel_url: str | None, chat_url: str | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    links_row: list[InlineKeyboardButton] = []
    if channel_url:
        links_row.append(InlineKeyboardButton(text="Канал", url=channel_url))
    if chat_url:
        links_row.append(InlineKeyboardButton(text="GDPX Academic | Чат", url=chat_url))
    if links_row:
        rows.append(links_row)
    rows.append(
        [
            InlineKeyboardButton(text="📘 FAQ", callback_data=CB_SELLER_INFO_FAQ),
            InlineKeyboardButton(text="🧭 Мануалы", callback_data=CB_SELLER_INFO_MANUALS),
        ]
    )
    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data=CB_SELLER_INFO_ROOT)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _info_root_text() -> str:
    return (
        "Справка · Центр помощи\n\n"
        "Что внутри:\n"
        "• Канал с обновлениями\n"
        "• Чат сообщества\n"
        "• FAQ по частым вопросам\n"
        "• Мануалы по шагам\n\n"
        "Выбери нужный раздел кнопками ниже."
    )


async def _route_admin_menu_from_seller_fsm(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Сбрасывает FSM продавца и открывает админ-панель."""

    if message.text is None or message.from_user is None:
        return
    from src.handlers.admin import on_admin_panel

    await state.clear()
    await on_admin_panel(message, session)


def _is_admin_menu_shortcut(text: str | None) -> bool:
    if text is None:
        return False
    return text.strip().casefold() == "/admin"


def _is_start_shortcut(text: str | None) -> bool:
    if text is None:
        return False
    return text.strip().casefold().startswith("/start")


async def _route_start_from_seller_fsm(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Сбрасывает seller FSM и запускает обычный /start сценарий."""

    from src.handlers.start import on_start

    await state.clear()
    await on_start(message, state, session)


def _render_profile_text(user, dashboard: dict) -> str:
    return _renderer.render_user_profile(
        {
            "username": user.username or "resident",
            "user_id": user.telegram_id,
            "approved_count": int(dashboard.get("accepted", 0)),
            "pending_count": int(dashboard.get("pending", 0)),
            "rejected_count": int(dashboard.get("rejected", 0)),
        }
    )


def _captcha_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пройти капчу", callback_data=CB_CAPTCHA_START)],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=CB_CAPTCHA_CANCEL)],
        ]
    )


def _seller_fsm_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить операцию", callback_data=CB_SELLER_CANCEL_FSM)],
        ]
    )


def _batch_action_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data=CB_SELLER_BATCH_SEND),
                InlineKeyboardButton(text="🗑 Отклонить", callback_data=CB_SELLER_BATCH_REJECT),
            ],
            [InlineKeyboardButton(text="❌ Отменить операцию", callback_data=CB_SELLER_CANCEL_FSM)],
        ]
    )


def _batch_csv_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📄 Скачать CSV", callback_data=CB_SELLER_BATCH_CSV_YES),
                InlineKeyboardButton(text="Без CSV", callback_data=CB_SELLER_BATCH_CSV_NO),
            ],
        ]
    )


def _batch_status_text(*, accepted: int, rejected: int) -> str:
    if accepted <= 1 and rejected == 0:
        return (
            "Материал отправлен на модерацию. Можешь отправить ещё фото или архив "
            "(удобно с подписью +79999999999 в том же сообщении — сразу на модерацию)."
        )
    return f"Добавлено: {accepted} шт. | Отклонено: {rejected} шт."


async def _show_batch_action_menu_after_idle(message: Message, state: FSMContext, user_id: int) -> None:
    await asyncio.sleep(3)
    data = await state.get_data()
    status_msg_id = data.get("batch_status_msg_id")
    if not status_msg_id:
        return
    try:
        await message.bot.edit_message_reply_markup(
            chat_id=message.chat.id,
            message_id=int(status_msg_id),
            reply_markup=_batch_action_keyboard(),
        )
    except TelegramAPIError:
        return


def _schedule_batch_idle_menu(message: Message, state: FSMContext, user_id: int) -> None:
    prev = _batch_idle_tasks.get(user_id)
    if prev is not None and not prev.done():
        prev.cancel()
    _batch_idle_tasks[user_id] = asyncio.create_task(_show_batch_action_menu_after_idle(message, state, user_id))


async def _refresh_batch_status_message(message: Message, state: FSMContext, *, show_actions: bool = False) -> None:
    data = await state.get_data()
    accepted = int(data.get("batch_accepted", 0))
    rejected = int(data.get("batch_rejected", 0))
    status_msg_id = data.get("batch_status_msg_id")
    text = _batch_status_text(accepted=accepted, rejected=rejected)
    keyboard = _batch_action_keyboard() if show_actions else None

    if status_msg_id:
        try:
            await message.bot.edit_message_text(
                text=text,
                chat_id=message.chat.id,
                message_id=int(status_msg_id),
                reply_markup=keyboard,
            )
            return
        except TelegramAPIError:
            pass

    sent = await message.answer(text=text, reply_markup=keyboard)
    await state.update_data(batch_status_msg_id=sent.message_id)


async def _batch_inc(state: FSMContext, key: str, delta: int = 1) -> None:
    data = await state.get_data()
    current = int(data.get(key, 0))
    await state.update_data(**{key: current + delta})


def _normalize_phone_batch(raw: str | None) -> str | None:
    strict = normalize_phone_strict(raw or "")
    if strict is not None:
        return strict
    digits = re.sub(r"\D+", "", raw or "")
    if not digits:
        return None
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    if len(digits) == 11 and digits.startswith("7"):
        return f"+{digits}"
    return None


async def _batch_add_row(state: FSMContext, *, status: str, phone: str | None, reason: str) -> None:
    data = await state.get_data()
    rows = list(data.get("batch_rows", []))
    rows.append(
        {
            "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "status": status,
            "phone": phone or "",
            "reason": reason,
        }
    )
    await state.update_data(batch_rows=rows)


async def _batch_reject(state: FSMContext, *, reason_code: str, phone: str | None = None) -> None:
    await _batch_inc(state, "batch_rejected", 1)
    data = await state.get_data()
    reasons = dict(data.get("batch_reject_reasons", {}))
    reasons[reason_code] = int(reasons.get(reason_code, 0)) + 1
    await state.update_data(batch_reject_reasons=reasons)
    await _batch_add_row(
        state,
        status="rejected",
        phone=phone,
        reason=REJECT_LABELS.get(reason_code, reason_code),
    )


async def _batch_accept(state: FSMContext, *, phone: str) -> None:
    await _batch_inc(state, "batch_accepted", 1)
    await _batch_add_row(state, status="accepted", phone=phone, reason="")


async def _batch_mark_seen_or_duplicate(state: FSMContext, *, phone: str, file_unique_id: str) -> bool:
    data = await state.get_data()
    seen_numbers = set(str(x) for x in data.get("batch_seen_numbers", []))
    seen_files = set(str(x) for x in data.get("batch_seen_file_uids", []))
    if phone in seen_numbers or file_unique_id in seen_files:
        return True
    seen_numbers.add(phone)
    seen_files.add(file_unique_id)
    await state.update_data(
        batch_seen_numbers=sorted(seen_numbers),
        batch_seen_file_uids=sorted(seen_files),
    )
    return False


def _batch_report_text(accepted: int, rejected: int, reasons: dict[str, int] | None = None) -> str:
    total = accepted + rejected
    lines = [
        "📦 Загрузка завершена.\n\n"
        f"Всего обработано: <b>{total}</b>\n"
        f"✅ Принято: <b>{accepted}</b>\n"
        f"❌ Отклонено: <b>{rejected}</b>"
    ]
    if reasons:
        lines.append("\n\nПричины отклонений:")
        for code, label in REJECT_LABELS.items():
            cnt = int(reasons.get(code, 0))
            if cnt > 0:
                lines.append(f"• {label}: <b>{cnt}</b>")
    return "".join(lines)


def _batch_csv_file(rows: list[dict[str, str]]) -> BufferedInputFile:
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(["time", "status", "phone", "reason"])
    for row in rows:
        writer.writerow([
            row.get("time", ""),
            row.get("status", ""),
            row.get("phone", ""),
            row.get("reason", ""),
        ])
    content = buf.getvalue().encode("utf-8-sig")
    filename = f"batch_report_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.csv"
    return BufferedInputFile(content, filename=filename)


def _seller_fsm_categories_keyboard(categories) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=str(category.title), callback_data=f"{CB_SELLER_FSM_CAT}:{category.id}")]
        for category in categories
    ]
    rows.append([InlineKeyboardButton(text="❌ Отменить операцию", callback_data=CB_SELLER_CANCEL_FSM)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _safe_delete_message(message: Message | None) -> None:
    if message is None:
        return
    try:
        await message.delete()
    except Exception:
        pass


async def _send_fsm_step_message(
    message: Message,
    state: FSMContext,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> Message:
    """Send next FSM prompt and remove previous bot prompt only after success."""

    state_data = await state.get_data()
    prev_last_msg_id = state_data.get("last_msg_id")
    sent = await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
    await state.update_data(last_msg_id=sent.message_id)
    if prev_last_msg_id:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=int(prev_last_msg_id))
        except Exception:
            pass
    return sent


@router.message(Command("profile"))
@router.message(F.text.in_({"Профиль", "ПРОФИЛЬ"}))
async def on_profile(message: Message, session: AsyncSession) -> None:
    """Показывает профиль продавца в формате компактного дашборда."""

    if message.from_user is None:
        return

    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer("Сначала пройди регистрацию через /start.")
        return

    dashboard = await SubmissionService(session=session).get_user_dashboard_stats(user_id=user.id)
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
    dashboard = await SubmissionService(session=session).get_user_dashboard_stats(user_id=user.id)
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
    """Показывает дашборд статистики селлера."""

    if message.from_user is None:
        return

    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer("Сначала пройди регистрацию через /start.")
        return

    stats = await SubmissionService(session=session).get_user_esim_seller_stats(user_id=user.id, days=1)
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
    stats = await SubmissionService(session=session).get_user_esim_seller_stats(user_id=user.id, days=days)
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            _format_seller_stats_dashboard(user, stats, period_label=period_label),
            reply_markup=_stats_period_keyboard(active_period="week" if period == "week" else "today"),
        )


def _seller_material_nav_keyboard(category_id: int, page: int, total: int) -> InlineKeyboardMarkup:
    max_page = (max(total, 1) - 1) // SELLER_PAGE_SIZE
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{CB_SELLER_MAT_PAGE}:{category_id}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP))
    if page < max_page:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{CB_SELLER_MAT_PAGE}:{category_id}:{page + 1}"))
    return InlineKeyboardMarkup(inline_keyboard=[nav] if nav else [])


def _material_status_badge(status: SubmissionStatus) -> str:
    if status == SubmissionStatus.PENDING:
        return "⏳"
    if status == SubmissionStatus.IN_REVIEW:
        return "🔎"
    if status == SubmissionStatus.ACCEPTED:
        return "✅"
    return "❌"


def _material_status_label(status: SubmissionStatus) -> str:
    if status == SubmissionStatus.PENDING:
        return "В очереди"
    if status == SubmissionStatus.IN_REVIEW:
        return "В работе"
    if status == SubmissionStatus.ACCEPTED:
        return "Зачёт"
    return "Незачёт"


def _material_status_tag(status: SubmissionStatus) -> str:
    if status == SubmissionStatus.PENDING:
        return "#pending"
    if status == SubmissionStatus.IN_REVIEW:
        return "#in_review"
    if status == SubmissionStatus.ACCEPTED:
        return "#accepted"
    return "#rejected"


def _material_short_preview(text: str, limit: int = 22) -> str:
    clean = (text or "").replace("\n", " ").strip()
    if not clean:
        return "без описания"
    if len(clean) <= limit:
        return clean
    return f"{clean[: limit - 1]}…"


def _material_phone_hint(text: str) -> str:
    digits = "".join(ch for ch in (text or "") if ch.isdigit())
    if len(digits) >= 4:
        return f"…{digits[-4:]}"
    return "…----"


def _material_filter_statuses(filter_key: str) -> list[SubmissionStatus] | None:
    if filter_key == MATERIAL_FILTER_ACTIVE:
        return [SubmissionStatus.PENDING, SubmissionStatus.IN_REVIEW]
    if filter_key == MATERIAL_FILTER_CREDIT:
        return [SubmissionStatus.ACCEPTED]
    if filter_key == MATERIAL_FILTER_DEBIT:
        return [SubmissionStatus.REJECTED, SubmissionStatus.BLOCKED, SubmissionStatus.NOT_A_SCAN]
    return None


def _material_filter_label(filter_key: str) -> str:
    return {
        MATERIAL_FILTER_ALL: "Все",
        MATERIAL_FILTER_ACTIVE: "В работе",
        MATERIAL_FILTER_CREDIT: "Зачёт",
        MATERIAL_FILTER_DEBIT: "Незачёт",
    }.get(filter_key, "Все")


def _parse_material_page_callback(data: str) -> tuple[int, int, str]:
    parts = data.split(":")
    category_id = int(parts[3])
    page = int(parts[4])
    filter_key = parts[5] if len(parts) > 5 else MATERIAL_FILTER_ALL
    if filter_key not in MATERIAL_FILTER_ORDER:
        filter_key = MATERIAL_FILTER_ALL
    return category_id, page, filter_key


def _parse_material_item_callback(data: str) -> tuple[int, int, int, str]:
    parts = data.split(":")
    submission_id = int(parts[3])
    category_id = int(parts[4])
    page = int(parts[5])
    filter_key = parts[6] if len(parts) > 6 else MATERIAL_FILTER_ALL
    if filter_key not in MATERIAL_FILTER_ORDER:
        filter_key = MATERIAL_FILTER_ALL
    return submission_id, category_id, page, filter_key


def _build_material_category_view(
    *,
    category_id: int,
    page: int,
    total: int,
    items: list[Submission],
    filter_key: str,
) -> tuple[str, InlineKeyboardMarkup]:
    max_page = (max(total, 1) - 1) // SELLER_PAGE_SIZE
    lines = [
        f"Материал · {_material_filter_label(filter_key)} · {page + 1}/{max_page + 1}",
        f"Показано: {len(items)} | Всего по фильтру: {total}",
        "",
    ]
    rows: list[list[InlineKeyboardButton]] = []

    for item in items:
        badge = _material_status_badge(item.status)
        tag = _material_status_tag(item.status)
        normalized_desc = (item.description_text or "").strip()
        phone_hint = _material_phone_hint(normalized_desc)
        short_desc = _material_short_preview(normalized_desc)
        lines.append(f"{badge} #{item.id:<4} {tag:<10} {phone_hint}  {short_desc}")
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Открыть #{item.id}",
                    callback_data=f"{CB_SELLER_MAT_ITEM}:{item.id}:{category_id}:{page}:{filter_key}",
                )
            ]
        )

    filter_row: list[InlineKeyboardButton] = []
    for key in MATERIAL_FILTER_ORDER:
        selected = "• " if key == filter_key else ""
        filter_row.append(
            InlineKeyboardButton(
                text=f"{selected}{_material_filter_label(key)}",
                callback_data=f"{CB_SELLER_MAT_FILTER}:{category_id}:{key}",
            )
        )
    rows.append(filter_row)
    nav_rows = _seller_material_nav_keyboard(category_id=category_id, page=page, total=total).inline_keyboard
    if nav_rows:
        nav_row = nav_rows[0]
        for i, button in enumerate(nav_row):
            if button.callback_data and button.callback_data.startswith(f"{CB_SELLER_MAT_PAGE}:"):
                nav_row[i] = InlineKeyboardButton(
                    text=button.text,
                    callback_data=f"{button.callback_data}:{filter_key}",
                )
        rows.append(nav_row)
    rows.append([InlineKeyboardButton(text="⬅️ К списку операторов", callback_data=CB_SELLER_MAT_BACK)])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == "Материал")
async def on_material_root(message: Message, session: AsyncSession) -> None:
    if message.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer("Сначала пройди регистрацию через /start.")
        return
    folders = await SubmissionService(session=session).get_user_material_folders(user.id)
    if not folders:
        await send_clean_text_screen(
            trigger_message=message,
            text="Материалов пока нет.",
            key="seller:material:root",
            reply_markup=seller_main_inline_keyboard(),
        )
        return
    rows = []
    for f in folders:
        text = f"{f['title']} ({f['total']})"
        rows.append([InlineKeyboardButton(text=text, callback_data=f"{CB_SELLER_MAT_CAT}:{f['category_id']}")])
    await send_clean_text_screen(
        trigger_message=message,
        text="Материал по операторам:",
        key="seller:material:root",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data == CB_SELLER_MENU_MATERIAL)
async def on_seller_menu_material(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return
    folders = await SubmissionService(session=session).get_user_material_folders(user.id)
    await callback.answer()
    if callback.message is None:
        return
    if not folders:
        await edit_message_text_safe(
            callback.message,
            "Материалов пока нет.",
            reply_markup=seller_main_inline_keyboard(),
        )
        return
    rows = []
    for f in folders:
        text = f"{f['title']} ({f['total']})"
        rows.append([InlineKeyboardButton(text=text, callback_data=f"{CB_SELLER_MAT_CAT}:{f['category_id']}")])
    await edit_message_text_safe(
        callback.message,
        "Материал по операторам:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def _send_material_category_page(
    message: Message,
    session: AsyncSession,
    *,
    user_id: int,
    category_id: int,
    page: int,
    filter_key: str = MATERIAL_FILTER_ALL,
) -> None:
    statuses = _material_filter_statuses(filter_key)
    items, total = await SubmissionService(session=session).list_user_material_by_category_paginated(
        user_id=user_id,
        category_id=category_id,
        page=page,
        page_size=SELLER_PAGE_SIZE,
        statuses=statuses,
    )
    if not items:
        await send_clean_text_screen(
            trigger_message=message,
            text="В этой папке пока нет товаров.",
            key=f"seller:material:category:{category_id}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ К списку операторов", callback_data=CB_SELLER_MAT_BACK)]]
            ),
        )
        return
    text, keyboard = _build_material_category_view(
        category_id=category_id,
        page=page,
        total=total,
        items=items,
        filter_key=filter_key,
    )
    await send_clean_text_screen(
        trigger_message=message,
        text=text,
        key=f"seller:material:category:{category_id}",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith(f"{CB_SELLER_MAT_CAT}:"))
async def on_material_category(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return
    category_id = int(callback.data.split(":")[3])
    await callback.answer()
    if callback.message is not None:
        filter_key = MATERIAL_FILTER_ALL
        statuses = _material_filter_statuses(filter_key)
        items, total = await SubmissionService(session=session).list_user_material_by_category_paginated(
            user_id=user.id,
            category_id=category_id,
            page=0,
            page_size=SELLER_PAGE_SIZE,
            statuses=statuses,
        )
        if not items:
            await edit_message_text_safe(
                callback.message,
                "В этой папке пока нет товаров.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="⬅️ К списку операторов", callback_data=CB_SELLER_MAT_BACK)]
                    ]
                ),
            )
            return
        text, keyboard = _build_material_category_view(
            category_id=category_id,
            page=0,
            total=total,
            items=items,
            filter_key=filter_key,
        )
        await edit_message_text_safe(callback.message, text, reply_markup=keyboard)


@router.callback_query(F.data.startswith(f"{CB_SELLER_MAT_PAGE}:"))
async def on_material_category_page(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return
    category_id, page, filter_key = _parse_material_page_callback(callback.data)
    await callback.answer()
    if callback.message is not None:
        page = max(page, 0)
        statuses = _material_filter_statuses(filter_key)
        items, total = await SubmissionService(session=session).list_user_material_by_category_paginated(
            user_id=user.id,
            category_id=category_id,
            page=page,
            page_size=SELLER_PAGE_SIZE,
            statuses=statuses,
        )
        if not items:
            await edit_message_text_safe(
                callback.message,
                "В этой папке пока нет товаров.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="⬅️ К списку операторов", callback_data=CB_SELLER_MAT_BACK)]
                    ]
                ),
            )
            return
        text, keyboard = _build_material_category_view(
            category_id=category_id,
            page=page,
            total=total,
            items=items,
            filter_key=filter_key,
        )
        await edit_message_text_safe(callback.message, text, reply_markup=keyboard)


@router.callback_query(F.data.startswith(f"{CB_SELLER_MAT_FILTER}:"))
async def on_material_category_filter(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return
    parts = callback.data.split(":")
    category_id = int(parts[3])
    filter_key = parts[4] if len(parts) > 4 else MATERIAL_FILTER_ALL
    if filter_key not in MATERIAL_FILTER_ORDER:
        filter_key = MATERIAL_FILTER_ALL
    statuses = _material_filter_statuses(filter_key)
    items, total = await SubmissionService(session=session).list_user_material_by_category_paginated(
        user_id=user.id,
        category_id=category_id,
        page=0,
        page_size=SELLER_PAGE_SIZE,
        statuses=statuses,
    )
    await callback.answer()
    if callback.message is not None:
        if not items:
            await edit_message_text_safe(
                callback.message,
                "В этой папке нет карточек по выбранному фильтру.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="⬅️ К списку операторов", callback_data=CB_SELLER_MAT_BACK)]
                    ]
                ),
            )
            return
        text, keyboard = _build_material_category_view(
            category_id=category_id,
            page=0,
            total=total,
            items=items,
            filter_key=filter_key,
        )
        await edit_message_text_safe(callback.message, text, reply_markup=keyboard)


@router.callback_query(F.data == CB_SELLER_MAT_BACK)
async def on_material_back_to_folders(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return
    folders = await SubmissionService(session=session).get_user_material_folders(user.id)
    if not folders:
        await callback.answer("Материалов пока нет", show_alert=True)
        return
    rows = []
    for f in folders:
        text = f"{f['title']} ({f['total']})"
        rows.append([InlineKeyboardButton(text=text, callback_data=f"{CB_SELLER_MAT_CAT}:{f['category_id']}")])
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            "Материал по операторам:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )


@router.callback_query(F.data.startswith(f"{CB_SELLER_MAT_ITEM}:"))
async def on_material_item(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return
    submission_id, category_id, page, filter_key = _parse_material_item_callback(callback.data)
    submission = await session.get(Submission, submission_id)
    if submission is None or submission.user_id != user.id:
        await callback.answer("Симка не найдена", show_alert=True)
        return
    can_edit = submission.status == SubmissionStatus.PENDING
    can_delete = submission.status in SELLER_DELETABLE_STATUSES
    rows: list[list[InlineKeyboardButton]] = []
    if can_edit:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Редактировать",
                    callback_data=f"{CB_SELLER_MAT_EDIT}:{submission.id}:{category_id}:{page}:{filter_key}",
                ),
                InlineKeyboardButton(
                    text="Обновить медиа",
                    callback_data=f"{CB_SELLER_MAT_EDIT_MEDIA}:{submission.id}",
                ),
            ]
        )
    if can_delete:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Удалить",
                    callback_data=f"{CB_SELLER_MAT_DELETE}:{submission.id}:{category_id}:{page}:{filter_key}",
                )
            ]
        )
    await callback.answer()
    if callback.message is not None:
        caption = (
            f"Симка #{submission.id}\n"
            f"Статус: {_material_status_label(submission.status)} ({_material_status_tag(submission.status)})\n"
            f"Описание: {(submission.description_text or '').strip()}\n"
            f"Редактирование: {'доступно' if can_edit else 'только для pending'}\n"
            f"Удаление: {'доступно' if can_delete else 'недоступно'}"
        )
        try:
            await bot_send_submission(
                bot=callback.bot,
                chat_id=callback.message.chat.id,
                submission=submission,
                caption=caption,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None,
            )
        except TelegramAPIError:
            await callback.message.answer(
                caption,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None,
            )


@router.callback_query(F.data.startswith(f"{CB_SELLER_MAT_EDIT}:"))
async def on_material_item_edit_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return
    parts = callback.data.split(":")
    submission_id = int(parts[3])
    category_id = int(parts[4])
    page = int(parts[5])
    filter_key = parts[6] if len(parts) > 6 else MATERIAL_FILTER_ALL
    if filter_key not in MATERIAL_FILTER_ORDER:
        filter_key = MATERIAL_FILTER_ALL
    submission = await session.get(Submission, submission_id)
    if submission is None or submission.user_id != user.id or submission.status != SubmissionStatus.PENDING:
        await callback.answer("Редактирование доступно только для pending", show_alert=True)
        return
    await state.set_state(SubmissionState.waiting_for_material_edit_description)
    await state.update_data(
        material_edit_submission_id=submission_id,
        material_category_id=category_id,
        material_page=page,
        material_filter=filter_key,
    )
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer("Отправь новый номер в формате +79999999999")


@router.callback_query(F.data.startswith(f"{CB_SELLER_MAT_EDIT_MEDIA}:"))
async def on_material_item_edit_media_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return
    _, _, _, submission_id_raw = callback.data.split(":")
    submission = await session.get(Submission, int(submission_id_raw))
    if submission is None or submission.user_id != user.id or submission.status != SubmissionStatus.PENDING:
        await callback.answer("Обновление медиа доступно только для pending", show_alert=True)
        return
    await state.set_state(SubmissionState.waiting_for_material_edit_media)
    await state.update_data(material_edit_submission_id=int(submission_id_raw))
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer("Отправь новое фото или архив-файл для симки.")


@router.message(SubmissionState.waiting_for_material_edit_description, F.text)
async def on_material_item_edit_submit(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.from_user is None or message.text is None:
        return
    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if user is None:
        await state.clear()
        return
    description_text = normalize_phone_strict(message.text)
    if description_text is None:
        await message.answer(PHONE_NORM_ERROR_HTML, parse_mode="HTML")
        return
    data = await state.get_data()
    submission_id = int(data.get("material_edit_submission_id", 0))
    updated = await SubmissionService(session=session).update_submission_description_for_seller(
        submission_id=submission_id,
        user_id=user.id,
        new_description=description_text,
    )
    await state.clear()
    if updated is None:
        await message.answer("Не удалось обновить симку (только pending).")
        return
    await message.answer(f"Симка #{updated.id} обновлена.")


@router.message(SubmissionState.waiting_for_material_edit_media, F.photo)
async def on_material_item_edit_media_photo(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if message.from_user is None or not message.photo:
        return
    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if user is None:
        await state.clear()
        return
    data = await state.get_data()
    submission_id = int(data.get("material_edit_submission_id", 0))
    photo = message.photo[-1]
    image_sha256 = hashlib.sha256(photo.file_unique_id.encode()).hexdigest()
    updated = await SubmissionService(session=session).update_submission_media_for_seller(
        submission_id=submission_id,
        user_id=user.id,
        telegram_file_id=photo.file_id,
        file_unique_id=photo.file_unique_id,
        image_sha256=image_sha256,
        attachment_type=ATTACHMENT_PHOTO,
    )
    await state.clear()
    await message.answer("Медиа обновлено." if updated else "Не удалось обновить (только pending).")


@router.message(SubmissionState.waiting_for_material_edit_media, F.document)
async def on_material_item_edit_media_document(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if message.from_user is None or message.document is None:
        return
    if not is_allowed_archive_document(message.document):
        await message.answer("Пришли архив файлом (zip/rar/7z/...).")
        return
    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if user is None:
        await state.clear()
        return
    data = await state.get_data()
    submission_id = int(data.get("material_edit_submission_id", 0))
    doc = message.document
    image_sha256 = hashlib.sha256(doc.file_unique_id.encode()).hexdigest()
    updated = await SubmissionService(session=session).update_submission_media_for_seller(
        submission_id=submission_id,
        user_id=user.id,
        telegram_file_id=doc.file_id,
        file_unique_id=doc.file_unique_id,
        image_sha256=image_sha256,
        attachment_type=ATTACHMENT_DOCUMENT,
    )
    await state.clear()
    await message.answer("Медиа обновлено." if updated else "Не удалось обновить (только pending).")


@router.callback_query(F.data.startswith(f"{CB_SELLER_MAT_DELETE}:"))
async def on_material_item_delete_ask(callback: CallbackQuery) -> None:
    if callback.data is None:
        return
    parts = callback.data.split(":")
    submission_id_raw = parts[3]
    category_id_raw = parts[4]
    page_raw = parts[5]
    filter_key = parts[6] if len(parts) > 6 else MATERIAL_FILTER_ALL
    if filter_key not in MATERIAL_FILTER_ORDER:
        filter_key = MATERIAL_FILTER_ALL
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            "Подтвердить удаление?",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Удалить",
                            callback_data=(
                                f"{CB_SELLER_MAT_DELETE_CONFIRM}:{submission_id_raw}:{category_id_raw}:"
                                f"{page_raw}:{filter_key}"
                            ),
                        )
                    ]
                ]
            ),
        )


@router.callback_query(F.data.startswith(f"{CB_SELLER_MAT_DELETE_CONFIRM}:"))
async def on_material_item_delete_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return
    parts = callback.data.split(":")
    submission_id_raw = parts[3]
    category_id_raw = parts[4]
    page_raw = parts[5]
    filter_key = parts[6] if len(parts) > 6 else MATERIAL_FILTER_ALL
    if filter_key not in MATERIAL_FILTER_ORDER:
        filter_key = MATERIAL_FILTER_ALL
    ok = await SubmissionService(session=session).delete_submission_for_seller(
        submission_id=int(submission_id_raw),
        user_id=user.id,
    )
    await callback.answer(
        "Удалено" if ok else "Удаление доступно только для pending/rejected/blocked/not_a_scan",
        show_alert=not ok,
    )
    if ok and callback.message is not None:
        await _send_material_category_page(
            callback.message,
            session,
            user_id=user.id,
            category_id=int(category_id_raw),
            page=max(int(page_raw), 0),
            filter_key=filter_key,
        )


def _seller_payout_history_kb(page: int, total: int) -> InlineKeyboardMarkup:
    max_page = (max(total, 1) - 1) // SELLER_PAGE_SIZE
    rows: list[list[InlineKeyboardButton]] = []
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{CB_SELLER_PAYHIST_PAGE}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP))
    if page < max_page:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{CB_SELLER_PAYHIST_PAGE}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data=CB_SELLER_MENU_PROFILE)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_payout_history_page(message: Message, session: AsyncSession, *, user_id: int, page: int) -> None:
    items, total = await BillingService(session=session).get_user_payout_history_paginated(
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


@router.message(F.text.func(is_sell_esim_button))
async def on_sell_content(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Стартует FSM-флоу продажи: категория -> фото -> описание."""

    categories = await CategoryService(session=session).get_active_categories()
    if not categories:
        await message.answer("Сейчас нет активных категорий. Попробуй позже.")
        return

    await state.set_state(SubmissionState.waiting_for_category)
    await send_clean_text_screen(
        trigger_message=message,
        key="seller:sell:start",
        text=FSMProgressFormatter.format_fsm_message(
            current_step=1,
            include_progress_bar=True,
            include_description=True,
            full_description=True,
        ),
        reply_markup=_seller_fsm_categories_keyboard(categories),
        parse_mode="HTML",
    )


@router.callback_query(F.data == CB_SELLER_MENU_SELL)
async def on_seller_menu_sell(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    categories = await CategoryService(session=session).get_active_categories()
    if not categories:
        await callback.answer("Сейчас нет активных категорий", show_alert=True)
        return
    await state.set_state(SubmissionState.waiting_for_category)
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            "Продать eSIM\n\nШаг 1/3: выбери категорию (оператора).\nПосле выбора сразу переходишь к загрузке симки.",
            reply_markup=_seller_fsm_categories_keyboard(categories),
        )


@router.callback_query(F.data == CB_SELLER_MENU_QUICK_ADD)
async def on_seller_menu_quick_add(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Быстрое добавление: категория -> фото -> готово (без описания)."""

    categories = await CategoryService(session=session).get_active_categories()
    if not categories:
        await callback.answer("Сейчас нет активных категорий", show_alert=True)
        return
    await state.set_state(SubmissionState.waiting_for_category)
    await state.update_data(quick_add=True)  # Флаг для быстрого режима
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            "⚡ Быстрое добавление\n\nВыбери категорию → загрузи фото → готово!",
            reply_markup=_seller_fsm_categories_keyboard(categories),
        )


@router.callback_query(
    F.data.startswith(f"{CB_SELLER_FSM_CAT}:"),
    StateFilter(SubmissionState.waiting_for_category),
)
async def on_seller_fsm_category_pick(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    try:
        category_id = int(callback.data.split(":")[3])
    except (TypeError, ValueError):
        await callback.answer("Некорректная категория", show_alert=True)
        return
    category = await CategoryService(session=session).get_by_id(category_id)
    if category is None or not category.is_active:
        await callback.answer("Категория недоступна", show_alert=True)
        return
    await state.update_data(
        category_id=category.id,
        batch_accepted=0,
        batch_rejected=0,
        batch_reject_reasons={},
        batch_rows=[],
        batch_seen_numbers=[],
        batch_seen_file_uids=[],
        batch_status_msg_id=None,
    )
    await state.set_state(SubmissionState.waiting_for_photo)
    await callback.answer()
    if callback.message is not None:
        data = await state.get_data()
        is_quick_add = data.get("quick_add", False)
        
        if is_quick_add:
            # QUICK ADD: минималистичное сообщение с прогрессом
            photo_text = FSMProgressFormatter.format_fsm_quick_message(current_step=2)
        else:
            # Обычный режим: полное сообщение с подробностями
            photo_text = FSMProgressFormatter.format_fsm_message(
                current_step=2,
                include_progress_bar=True,
                include_description=True,
                full_description=True,
            )
        
        await edit_message_text_safe(
            callback.message,
            photo_text,
            reply_markup=_seller_fsm_cancel_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(
    F.data == CB_SELLER_CANCEL_FSM,
    StateFilter(
        SubmissionState.waiting_for_category,
        SubmissionState.waiting_for_photo,
        SubmissionState.waiting_for_description,
        SubmissionState.waiting_for_batch_delete_phone,
        SubmissionState.waiting_for_batch_csv_choice,
    ),
)
async def on_seller_cancel_fsm(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if callback.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return
    await state.clear()
    dashboard = await SubmissionService(session=session).get_user_dashboard_stats(user_id=user.id)
    text = _renderer.render_user_profile(
        {
            "username": user.username or "resident",
            "user_id": user.telegram_id,
            "approved_count": int(dashboard.get("accepted", 0)),
            "pending_count": int(dashboard.get("pending", 0)),
            "rejected_count": int(dashboard.get("rejected", 0)),
        }
    )
    await callback.answer("Операция отменена")
    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            text,
            reply_markup=seller_main_inline_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(
    F.data.in_({CB_SELLER_FINISH_BATCH, CB_SELLER_BATCH_SEND}),
    StateFilter(
        SubmissionState.waiting_for_photo,
        SubmissionState.waiting_for_description,
    ),
)
async def on_seller_finish_batch(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if callback.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return

    data = await state.get_data()
    accepted = int(data.get("batch_accepted", 0))
    rejected = int(data.get("batch_rejected", 0))
    reasons = dict(data.get("batch_reject_reasons", {}))
    rows = list(data.get("batch_rows", []))

    await state.update_data(batch_final_accepted=accepted, batch_final_rejected=rejected, batch_final_reasons=reasons)
    await state.set_state(SubmissionState.waiting_for_batch_csv_choice)

    await callback.answer("Загрузка завершена")
    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            _batch_report_text(accepted, rejected, reasons),
            parse_mode="HTML",
            reply_markup=_batch_csv_choice_keyboard(),
        )


@router.callback_query(F.data == CB_SELLER_BATCH_REJECT, StateFilter(SubmissionState.waiting_for_photo))
async def on_seller_batch_reject_request(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SubmissionState.waiting_for_batch_delete_phone)
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            "Введи номер телефона для удаления из всей БХ (например, +79999999999).",
            reply_markup=_seller_fsm_cancel_keyboard(),
        )


@router.message(SubmissionState.waiting_for_batch_delete_phone, F.text)
async def on_seller_batch_delete_phone(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.text is None:
        return
    phone = _normalize_phone_batch(message.text)
    if phone is None:
        await message.answer("Неверный формат номера. Введи номер в формате +79999999999.")
        return

    deleted = await SubmissionService(session=session).delete_by_phone_global(phone)
    await state.set_state(SubmissionState.waiting_for_photo)
    await message.answer(f"Удалено из БХ по номеру {phone}: {deleted} записей.")
    await _refresh_batch_status_message(message, state, show_actions=True)


@router.callback_query(F.data == CB_SELLER_BATCH_CSV_YES, StateFilter(SubmissionState.waiting_for_batch_csv_choice))
async def on_seller_batch_csv_yes(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if callback.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return

    data = await state.get_data()
    rows = list(data.get("batch_rows", []))
    await state.clear()

    dashboard = await SubmissionService(session=session).get_user_dashboard_stats(user_id=user.id)
    profile_text = _renderer.render_user_profile(
        {
            "username": user.username or "resident",
            "user_id": user.telegram_id,
            "approved_count": int(dashboard.get("accepted", 0)),
            "pending_count": int(dashboard.get("pending", 0)),
            "rejected_count": int(dashboard.get("rejected", 0)),
        }
    )

    await callback.answer("CSV отправлен")
    if callback.message is not None:
        if rows:
            await callback.message.answer_document(
                document=_batch_csv_file(rows),
                caption="📄 CSV-отчёт по батчу",
            )
        await callback.message.answer(
            profile_text,
            reply_markup=seller_main_inline_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == CB_SELLER_BATCH_CSV_NO, StateFilter(SubmissionState.waiting_for_batch_csv_choice))
async def on_seller_batch_csv_no(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if callback.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return

    await state.clear()
    dashboard = await SubmissionService(session=session).get_user_dashboard_stats(user_id=user.id)
    profile_text = _renderer.render_user_profile(
        {
            "username": user.username or "resident",
            "user_id": user.telegram_id,
            "approved_count": int(dashboard.get("accepted", 0)),
            "pending_count": int(dashboard.get("pending", 0)),
            "rejected_count": int(dashboard.get("rejected", 0)),
        }
    )

    await callback.answer("Без CSV")
    if callback.message is not None:
        await callback.message.answer(
            profile_text,
            reply_markup=seller_main_inline_keyboard(),
            parse_mode="HTML",
        )


@router.message(SubmissionState.waiting_for_category)
async def on_category_selected(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Фиксирует выбранную категорию и запрашивает фото."""

    if message.text is None or message.from_user is None:
        return

    if _is_admin_menu_shortcut(message.text) and await AdminService(session=session).is_admin(message.from_user.id):
        await _route_admin_menu_from_seller_fsm(message, state, session)
        return

    text = message.text.strip()
    category = await CategoryService(session=session).get_by_title(text)
    if category is None:
        await message.answer("Выбери категорию кнопками ниже.")
        return

    await state.update_data(
        category_id=category.id,
        batch_accepted=0,
        batch_rejected=0,
        batch_reject_reasons={},
        batch_rows=[],
        batch_seen_numbers=[],
        batch_seen_file_uids=[],
        batch_status_msg_id=None,
    )
    await state.set_state(SubmissionState.waiting_for_photo)
    await message.answer(
        text=FSMProgressFormatter.format_fsm_message(
            current_step=2,
            include_progress_bar=True,
            include_description=True,
            full_description=True,
        ),
        reply_markup=_seller_fsm_cancel_keyboard(),
        parse_mode="HTML",
    )


async def _upload_prechecks(
    user,
    submission_service: SubmissionService,
    state: FSMContext,
    message: Message,
    session: AsyncSession,
) -> bool:
    """Общие проверки перед приёмом файла. Возвращает True, если можно продолжать."""

    if user.is_restricted:
        await state.clear()
        await message.answer(
            "У тебя временное ограничение. Подтверди, что ты человек.",
            reply_markup=_captcha_keyboard(),
        )
        return False
    if user.duplicate_timeout_until and user.duplicate_timeout_until > datetime.now(timezone.utc):
        await state.clear()
        await message.answer(
            f"Временный таймаут за дубликаты до {user.duplicate_timeout_until}.",
            reply_markup=seller_main_inline_keyboard(),
        )
        return False
    data = await state.get_data()
    raw_cid = data.get("category_id")
    if raw_cid is None:
        await state.clear()
        await message.answer(
            "Сначала выбери категорию (подтип оператора).",
            reply_markup=seller_main_inline_keyboard(),
        )
        return False
    category_id = int(raw_cid)

    quota_svc = SellerQuotaService(session=session)
    daily_limit = await quota_svc.get_quota_for_today(user.id, category_id)
    if daily_limit <= 0:
        await state.clear()
        await message.answer(
            "На сегодня в этой категории не назначен лимит выгрузок. "
            "Администратор задаёт лимиты через /adm_cat.",
            reply_markup=seller_main_inline_keyboard(),
        )
        return False
    counts = await submission_service.get_daily_counts_by_category_for_user(user_id=user.id)
    daily_count = counts.get(category_id, 0)
    if daily_count >= daily_limit:
        await state.clear()
        await message.answer(
            f"Достигнут дневной лимит по запросу в этой категории: {daily_limit}. "
            "Новые симки — завтра (UTC) или после смены запроса.",
            reply_markup=seller_main_inline_keyboard(),
        )
        return False
    return True


async def _finalize_submission_after_upload(
    *,
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    user,
    category_id: int,
    telegram_file_id: str,
    file_unique_id: str,
    image_sha256: str,
    attachment_type: str,
    description_text: str,
    stay_in_batch: bool,
) -> bool:
    """Создаёт submission. При stay_in_batch остаёмся на шаге «фото» для следующей симки."""

    category_service = CategoryService(session=session)
    selected_category = await category_service.get_by_id(category_id)
    if selected_category is None:
        await state.clear()
        await message.answer(
            "Категория не найдена. Начни заново.",
            reply_markup=seller_main_inline_keyboard(),
        )
        return False
    if selected_category.total_upload_limit is not None:
        current_total = await category_service.get_total_uploaded_count(selected_category.id)
        if current_total >= selected_category.total_upload_limit:
            await state.clear()
            await message.answer(
                f"По категории достигнут общий лимит: {selected_category.total_upload_limit}.",
                reply_markup=seller_main_inline_keyboard(),
            )
            return False

    submission = await SubmissionService(session=session).create_submission(
        user_id=user.id,
        category_id=selected_category.id,
        telegram_file_id=str(telegram_file_id),
        file_unique_id=str(file_unique_id),
        image_sha256=str(image_sha256),
        description_text=description_text,
        attachment_type=attachment_type,
    )
    await _batch_accept(state, phone=description_text)

    if stay_in_batch:
        await state.update_data(
            telegram_file_id=None,
            file_unique_id=None,
            image_sha256=None,
            attachment_type=ATTACHMENT_PHOTO,
        )
        await state.set_state(SubmissionState.waiting_for_photo)
        await _refresh_batch_status_message(message, state)
        if message.from_user is not None:
            _schedule_batch_idle_menu(message, state, message.from_user.id)
    else:
        await state.clear()
        dashboard = await SubmissionService(session=session).get_user_dashboard_stats(user_id=user.id)
        await message.answer(
            text=_renderer.render_user_profile(
                {
                    "username": user.username or "resident",
                    "user_id": user.telegram_id,
                    "approved_count": int(dashboard.get("accepted", 0)),
                    "pending_count": int(dashboard.get("pending", 0)),
                    "rejected_count": int(dashboard.get("rejected", 0)),
                }
            ),
            reply_markup=seller_main_inline_keyboard(),
            parse_mode="HTML",
        )
    return True


async def _store_file_and_ask_description(
    state: FSMContext,
    message: Message,
    session: AsyncSession,
    submission_service: SubmissionService,
    user,
    file_id: str,
    file_unique_id: str,
    attachment_type: str,
) -> None:
    """Сохраняет хэш и переводит на шаг описания."""

    image_sha256 = hashlib.sha256(file_unique_id.encode()).hexdigest()

    if await submission_service.is_duplicate_accepted(image_sha256=image_sha256):
        await UserService(session=session).set_duplicate_timeout(user_id=user.id, minutes=60)
        await state.clear()
        await message.answer(
            "Эта симка уже была принята ранее. Выдан таймаут 60 минут и ограничение до прохождения капчи.",
            reply_markup=seller_main_inline_keyboard(),
        )
        return

    await state.update_data(
        telegram_file_id=file_id,
        file_unique_id=file_unique_id,
        image_sha256=image_sha256,
        attachment_type=attachment_type,
    )
    await state.set_state(SubmissionState.waiting_for_description)
    data = await state.get_data()
    is_quick_add = data.get("quick_add", False)
    
    if is_quick_add:
        # QUICK ADD: минималистичное сообщение с прогрессом
        desc_text = FSMProgressFormatter.format_fsm_quick_message(current_step=3)
    else:
        # Обычный режим: полное сообщение с прогрессом и подробностями
        desc_text = FSMProgressFormatter.format_fsm_message(
            current_step=3,
            include_progress_bar=True,
            include_description=True,
            full_description=True,
        )
    
    await _send_fsm_step_message(
        message,
        state,
        text=desc_text,
        reply_markup=_seller_fsm_cancel_keyboard(),
        parse_mode="HTML",
    )


@router.message(SubmissionState.waiting_for_photo, F.photo)
async def on_photo_received(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Проверяет лимит и дубликаты, затем принимает фото."""

    if message.from_user is None or not message.photo:
        return
    await _safe_delete_message(message)

    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if user is None:
        await state.clear()
        await message.answer("Сначала пройди регистрацию через /start.")
        return

    submission_service = SubmissionService(session=session)
    if not await _upload_prechecks(user, submission_service, state, message, session):
        return

    data = await state.get_data()
    category_id = int(data["category_id"])

    best_photo = message.photo[-1]
    image_sha256 = hashlib.sha256(best_photo.file_unique_id.encode()).hexdigest()

    caption = _normalize_phone_batch(message.caption or "")
    if caption is None:
        await _batch_reject(state, reason_code=REJECT_NO_NUMBER)
        await _refresh_batch_status_message(message, state)
        _schedule_batch_idle_menu(message, state, message.from_user.id)
        return

    if await _batch_mark_seen_or_duplicate(state, phone=caption, file_unique_id=best_photo.file_unique_id):
        await _batch_reject(state, reason_code=REJECT_DUPLICATE_BATCH, phone=caption)
        await _refresh_batch_status_message(message, state)
        _schedule_batch_idle_menu(message, state, message.from_user.id)
        return

    if await submission_service.is_duplicate_accepted(image_sha256=image_sha256):
        await UserService(session=session).set_duplicate_timeout(user_id=user.id, minutes=60)
        await state.clear()
        await message.answer(
            "Эта симка уже была принята ранее. Выдан таймаут 60 минут и ограничение до прохождения капчи.",
            reply_markup=seller_main_inline_keyboard(),
        )
        return
    await _finalize_submission_after_upload(
        message=message,
        state=state,
        session=session,
        bot=bot,
        user=user,
        category_id=category_id,
        telegram_file_id=best_photo.file_id,
        file_unique_id=best_photo.file_unique_id,
        image_sha256=image_sha256,
        attachment_type=ATTACHMENT_PHOTO,
        description_text=caption,
        stay_in_batch=True,
    )
    return


@router.message(SubmissionState.waiting_for_photo, F.document)
async def on_archive_document_received(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Принимает архив как документ (файл)."""

    if message.from_user is None or message.document is None:
        return
    await _safe_delete_message(message)

    document: Document = message.document
    if not is_allowed_archive_document(document):
        await _batch_reject(state, reason_code=REJECT_BAD_FILE)
        await _refresh_batch_status_message(message, state)
        _schedule_batch_idle_menu(message, state, message.from_user.id)
        return

    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if user is None:
        await state.clear()
        await message.answer("Сначала пройди регистрацию через /start.")
        return

    submission_service = SubmissionService(session=session)
    if not await _upload_prechecks(user, submission_service, state, message, session):
        return

    data = await state.get_data()
    category_id = int(data["category_id"])

    image_sha256 = hashlib.sha256(document.file_unique_id.encode()).hexdigest()

    caption = _normalize_phone_batch(message.caption or "")
    if caption is None:
        await _batch_reject(state, reason_code=REJECT_NO_NUMBER)
        await _refresh_batch_status_message(message, state)
        _schedule_batch_idle_menu(message, state, message.from_user.id)
        return

    if await _batch_mark_seen_or_duplicate(state, phone=caption, file_unique_id=document.file_unique_id):
        await _batch_reject(state, reason_code=REJECT_DUPLICATE_BATCH, phone=caption)
        await _refresh_batch_status_message(message, state)
        _schedule_batch_idle_menu(message, state, message.from_user.id)
        return

    if await submission_service.is_duplicate_accepted(image_sha256=image_sha256):
        await UserService(session=session).set_duplicate_timeout(user_id=user.id, minutes=60)
        await state.clear()
        await message.answer(
            "Эта симка уже была принята ранее. Выдан таймаут 60 минут и ограничение до прохождения капчи.",
            reply_markup=seller_main_inline_keyboard(),
        )
        return
    await _finalize_submission_after_upload(
        message=message,
        state=state,
        session=session,
        bot=bot,
        user=user,
        category_id=category_id,
        telegram_file_id=document.file_id,
        file_unique_id=document.file_unique_id,
        image_sha256=image_sha256,
        attachment_type=ATTACHMENT_DOCUMENT,
        description_text=caption,
        stay_in_batch=True,
    )
    return


@router.message(SubmissionState.waiting_for_photo)
async def on_photo_expected(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Подсказывает формат шага, если пришло не фото и не архив."""

    if (
        message.text
        and message.from_user is not None
        and _is_start_shortcut(message.text)
    ):
        await _route_start_from_seller_fsm(message, state, session)
        return

    if (
        message.text
        and message.from_user is not None
        and _is_admin_menu_shortcut(message.text)
        and await AdminService(session=session).is_admin(message.from_user.id)
    ):
        await _route_admin_menu_from_seller_fsm(message, state, session)
        return

    await message.answer(
        text=FSMProgressFormatter.format_fsm_quick_message(current_step=2),
        parse_mode="HTML",
        reply_markup=_seller_fsm_cancel_keyboard(),
    )


@router.message(SubmissionState.waiting_for_description, F.text)
async def on_description_received(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Сохраняет симку после получения описания."""

    if message.from_user is None or message.text is None:
        return
    await _safe_delete_message(message)

    if _is_start_shortcut(message.text):
        await _route_start_from_seller_fsm(message, state, session)
        return

    if _is_admin_menu_shortcut(message.text) and await AdminService(session=session).is_admin(message.from_user.id):
        await _route_admin_menu_from_seller_fsm(message, state, session)
        return

    # Новый режим загрузки: только готовые сообщения «медиа + номер».
    await state.set_state(SubmissionState.waiting_for_photo)
    await _batch_reject(state, reason_code=REJECT_NUMBER_WITHOUT_MEDIA)
    await _refresh_batch_status_message(message, state)
    _schedule_batch_idle_menu(message, state, message.from_user.id)


@router.message(
    CommandStart(ignore_mention=True),
    StateFilter(
        SubmissionState.waiting_for_category,
        SubmissionState.waiting_for_photo,
        SubmissionState.waiting_for_description,
        SubmissionState.waiting_for_batch_delete_phone,
        SubmissionState.waiting_for_batch_csv_choice,
        SubmissionState.waiting_for_material_edit_description,
        SubmissionState.waiting_for_material_edit_media,
    ),
)
async def on_start_inside_submission_fsm(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Позволяет всегда выйти из seller FSM по /start."""

    await _route_start_from_seller_fsm(message, state, session)


@router.message(SubmissionState.waiting_for_description)
async def on_description_expected(message: Message) -> None:
    """Подсказывает формат шага, если пришел не текст."""

    await message.answer(
        text=FSMProgressFormatter.format_fsm_quick_message(current_step=3),
        reply_markup=_seller_fsm_cancel_keyboard(),
        parse_mode="HTML",
    )


@router.message(F.text == "Поддержка")
async def on_support(message: Message, session: AsyncSession) -> None:
    if message.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer("Сначала пройди регистрацию через /start.")
        return
    support_link = "@GDPX1"

    text = (
        "Support / Помощь\n\n"
        "FAQ:\n"
        "• Если дубликат/таймаут: проверь, что симка не отправлялась ранее.\n"
        "• Если не зачёт: смотри статус в разделе «Материал».\n"
        "• Выплаты: история и суммы в разделе «История выплат».\n"
        "• Проблема с загрузкой: отправляй архив как файл.\n\n"
        f"Написать: {support_link}"
    )
    await send_clean_text_screen(
        trigger_message=message,
        text=text,
        key="seller:support",
        reply_markup=seller_main_inline_keyboard(),
    )


@router.callback_query(F.data == CB_SELLER_MENU_SUPPORT)
async def on_seller_menu_support(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return
    support_link = "@GDPX1"
    text = (
        "Support / Помощь\n\n"
        "FAQ:\n"
        "• Если дубликат/таймаут: проверь, что симка не отправлялась ранее.\n"
        "• Если не зачёт: смотри статус в разделе «Материал».\n"
        "• Выплаты: история и суммы в разделе «История выплат».\n"
        "• Проблема с загрузкой: отправляй архив как файл.\n\n"
        f"Написать: {support_link}"
    )
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(callback.message, text, reply_markup=seller_main_inline_keyboard())


@router.message(F.text.in_({"INFO", "Справка"}))
async def on_info_root(message: Message, session: AsyncSession) -> None:
    if message.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer("Сначала пройди регистрацию через /start.")
        return
    settings = get_settings()
    channel_url = settings.brand_channel_url
    chat_url = settings.brand_chat_url
    await send_clean_text_screen(
        trigger_message=message,
        text=_info_root_text(),
        key="seller:info",
        reply_markup=_info_root_keyboard(channel_url, chat_url),
    )


@router.callback_query(F.data == CB_SELLER_MENU_INFO)
async def on_seller_menu_info(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    settings = get_settings()
    channel_url = settings.brand_channel_url
    chat_url = settings.brand_chat_url
    await callback.answer()
    await edit_message_text_safe(
        callback.message,
        _info_root_text(),
        reply_markup=_info_root_keyboard(channel_url, chat_url),
    )


@router.callback_query(F.data == CB_SELLER_INFO_ROOT)
async def on_info_root_refresh(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    settings = get_settings()
    channel_url = settings.brand_channel_url
    chat_url = settings.brand_chat_url
    await callback.answer()
    await edit_message_text_safe(
        callback.message,
        _info_root_text(),
        reply_markup=_info_root_keyboard(channel_url, chat_url),
    )


@router.callback_query(F.data == CB_SELLER_INFO_FAQ)
async def on_info_faq(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    await edit_message_text_safe(
        callback.message,
        "FAQ · Быстрые ответы\n\n"
        "1) Как загрузить симку?\n"
        "Отправь фото или архив файлом.\n\n"
        "2) Какой формат номера?\n"
        "+79999999999\n\n"
        "3) Где смотреть итог?\n"
        "В разделе «Материал» и «История выплат».",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ В INFO", callback_data=CB_SELLER_INFO_ROOT)]]
        ),
    )


@router.callback_query(F.data == CB_SELLER_INFO_MANUALS)
async def on_info_manuals(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    await edit_message_text_safe(
        callback.message,
        "<b>🧭 Мануалы</b>\n\nВыбери раздел:",
        reply_markup=_manuals_list_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith(f"{CB_SELLER_MANUAL_OPEN}:"))
async def on_manual_open(callback: CallbackQuery) -> None:
    if callback.message is None or callback.data is None:
        return
    manual_id = callback.data.split(":")[3]
    card = get_manual_by_id(manual_id)
    if card is None:
        await callback.answer("Мануал не найден", show_alert=True)
        return
    await callback.answer()
    await edit_message_text_safe(
        callback.message,
        card.text,
        reply_markup=_manual_detail_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == CB_CAPTCHA_CANCEL)
async def on_captcha_cancel(callback: CallbackQuery, session: AsyncSession) -> None:
    """Снимает inline-капчу и возвращает главное меню."""

    if callback.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    await callback.answer()
    if callback.message is not None:
        dashboard = {"accepted": 0, "pending": 0, "rejected": 0}
        if user is not None:
            dashboard = await SubmissionService(session=session).get_user_dashboard_stats(user_id=user.id)
        text = _render_profile_text(user, dashboard) if user is not None else "Сначала пройди регистрацию через /start."
        await edit_message_text_safe(
            callback.message,
            text,
            reply_markup=seller_main_inline_keyboard() if user is not None else None,
            parse_mode="HTML" if user is not None else None,
        )


@router.callback_query(F.data == CB_CAPTCHA_START)
async def on_captcha_start(callback: CallbackQuery, session: AsyncSession) -> None:
    """Генерирует captcha-код и отправляет пользователю."""

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
            f"Введи код ниже отдельным сообщением:\n{answer}\n\nЭто упрощенная captcha для снятия ограничения.",
        )


@router.message(F.text.regexp(r"^\d{4}$"))
async def on_captcha_check(message: Message, session: AsyncSession) -> None:
    """Проверяет ввод captcha и снимает ограничение."""

    if message.from_user is None or message.text is None:
        return
    user_service = UserService(session=session)
    user = await user_service.get_by_telegram_id(message.from_user.id)
    if user is None or not user.is_restricted or not user.captcha_answer:
        return
    ok = await user_service.verify_captcha(user_id=user.id, answer=message.text.strip())
    if ok:
        dashboard = await SubmissionService(session=session).get_user_dashboard_stats(user_id=user.id)
        await message.answer(
            _render_profile_text(user, dashboard),
            reply_markup=seller_main_inline_keyboard(),
            parse_mode="HTML",
        )
        return
    await message.answer("Неверный код. Нажми 'Пройти капчу' и попробуй снова.", reply_markup=_captcha_keyboard())


@router.message(StateFilter(None), ~F.text.startswith("/"))
async def on_seller_fallback_cleanup(message: Message, session: AsyncSession) -> None:
    """Молча удаляет лишние сообщения вне FSM для чистого чата."""

    if message.from_user is not None and await AdminService(session=session).is_admin(message.from_user.id):
        return
    await _safe_delete_message(message)
