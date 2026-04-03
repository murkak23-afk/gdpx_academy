"""Shared constants, keyboard builders, and stateless utility functions.

This module is imported by all seller sub-modules. It must NOT import from
any other sellers sub-module to prevent circular dependencies.
"""

from __future__ import annotations

import asyncio
import csv
from datetime import datetime, timezone
from io import StringIO

from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.database.models.enums import SubmissionStatus
from src.keyboards.callbacks import (
    CB_CAPTCHA_CANCEL,
    CB_CAPTCHA_START,
    CB_SELLER_BATCH_REJECT,
    CB_SELLER_BATCH_SEND,
    CB_SELLER_BATCH_CSV_NO,
    CB_SELLER_BATCH_CSV_YES,
    CB_SELLER_CANCEL_FSM,
    CB_SELLER_FSM_CAT,
)
from src.utils.ui_builder import GDPXRenderer

# ── Constants ─────────────────────────────────────────────────────────────

SELLER_PAGE_SIZE = 5
DEFAULT_INFO_CHAT_URL = "https://t.me/+cFWhTnl_iew1ZjZi"
DIVIDER = "━━━━━━━━━━━━━━━━━━━━"

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

# ── Shared runtime state ──────────────────────────────────────────────────

_renderer = GDPXRenderer()
_batch_idle_tasks: dict[int, asyncio.Task] = {}

# ── Profile render ────────────────────────────────────────────────────────


def _render_profile_text(user, dashboard: dict) -> str:
    return _renderer.render_user_profile(
        {
            "username": user.username or "resident",
            "user_id": user.telegram_id,
            "approved_count": int(dashboard.get("accepted", 0)),
            "pending_count": int(dashboard.get("pending", 0)),
            "rejected_count": int(dashboard.get("rejected", 0)),
        },
        user.telegram_id,
    )


# ── FSM routing helpers ───────────────────────────────────────────────────


def _is_admin_menu_shortcut(text: str | None) -> bool:
    if text is None:
        return False
    return text.strip().casefold() == "/admin"


def _is_start_shortcut(text: str | None) -> bool:
    if text is None:
        return False
    return text.strip().casefold().startswith("/start")


async def _route_admin_menu_from_seller_fsm(
    message: Message,
    state: FSMContext,
    session,
) -> None:
    """Resets seller FSM and opens the admin panel."""
    from src.handlers.admin import on_admin_panel  # deferred to avoid circular import

    await state.clear()
    await on_admin_panel(message, session)


async def _route_start_from_seller_fsm(
    message: Message,
    state: FSMContext,
    session,
) -> None:
    """Resets seller FSM and runs the /start flow."""
    from src.handlers.start import on_start  # deferred to avoid circular import

    await state.clear()
    await on_start(message, state, session)


# ── Shared keyboards ──────────────────────────────────────────────────────


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


def _seller_fsm_categories_keyboard(categories) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=str(cat.title), callback_data=f"{CB_SELLER_FSM_CAT}:{cat.id}")]
        for cat in categories
    ]
    rows.append([InlineKeyboardButton(text="❌ Отменить операцию", callback_data=CB_SELLER_CANCEL_FSM)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Misc helpers ──────────────────────────────────────────────────────────


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
            await message.bot.delete_message(
                chat_id=message.chat.id, message_id=int(prev_last_msg_id)
            )
        except Exception:
            pass
    return sent


# ── Batch display helpers ─────────────────────────────────────────────────


def _batch_status_text(*, accepted: int, rejected: int) -> str:
    if accepted <= 1 and rejected == 0:
        return (
            "Материал отправлен на модерацию. Можешь отправить ещё фото или архив "
            "(удобно с подписью +79999999999 в том же сообщении — сразу на модерацию)."
        )
    return f"Добавлено: {accepted} шт. | Отклонено: {rejected} шт."


async def _show_batch_action_menu_after_idle(
    message: Message, state: FSMContext, user_id: int
) -> None:
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
    _batch_idle_tasks[user_id] = asyncio.create_task(
        _show_batch_action_menu_after_idle(message, state, user_id)
    )


async def _refresh_batch_status_message(
    message: Message, state: FSMContext, *, show_actions: bool = False
) -> None:
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


# ── Batch state utilities ─────────────────────────────────────────────────


async def _batch_inc(state: FSMContext, key: str, delta: int = 1) -> None:
    data = await state.get_data()
    current = int(data.get(key, 0))
    await state.update_data(**{key: current + delta})


def _normalize_phone_batch(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) > 11:
        digits = digits[:11]
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    if len(digits) == 11 and digits.startswith("7"):
        return digits
    return None


async def _batch_add_row(
    state: FSMContext, *, status: str, phone: str | None, reason: str
) -> None:
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


async def _batch_reject(
    state: FSMContext, *, reason_code: str, phone: str | None = None
) -> None:
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


async def _batch_mark_seen_or_duplicate(
    state: FSMContext, *, phone: str, file_unique_id: str
) -> bool:
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


def _batch_report_text(
    accepted: int, rejected: int, reasons: dict[str, int] | None = None
) -> str:
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
        writer.writerow(
            [
                row.get("time", ""),
                row.get("status", ""),
                row.get("phone", ""),
                row.get("reason", ""),
            ]
        )
    content = buf.getvalue().encode("utf-8-sig")
    filename = f"batch_report_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.csv"
    return BufferedInputFile(content, filename=filename)
