from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html import escape
from io import BytesIO, StringIO

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    Message,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.enums import PayoutStatus, SubmissionStatus
from src.database.models.publication import Payout
from src.database.models.submission import Submission
from src.database.models.user import User
from src.keyboards import REPLY_BTN_BACK, payout_confirm_keyboard, payout_final_confirm_keyboard
from src.keyboards.admin_hints import HINT_PAYOUTS
from src.keyboards.constants import CALLBACK_INLINE_BACK
from src.keyboards.callbacks import (
    CB_NOOP,
    CB_PAY_CANCEL,
    CB_PAY_CONFIRM,
    CB_PAY_FINAL_CONFIRM,
    CB_PAY_HISTORY_PAGE,
    CB_PAY_LEDGER_PAGE,
    CB_PAY_MARK,
    CB_PAY_PENDING_DELETE,
    CB_PAY_PENDING_PAGE,
    CB_PAY_TOPUP,
    CB_PAY_TOPUP_CHECK,
    CB_PAY_TRASH,
    CB_PAY_TRASH_PAGE,
)
from src.services import (
    AdminAuditService,
    AdminService,
    BillingService,
    CryptoBotService,
    UserService,
)
from src.states.admin_state import AdminPayoutState
from src.utils.text_format import edit_message_text_safe

router = Router(name="admin-payouts-router")

PAGE_SIZE = 5
LEDGER_PAGE_SIZE = 8
_ADMIN_LAST_PANEL_MSG_KEY = "admin_last_panel_message_id"


def _parse_pay_uid_page(callback_data: str) -> tuple[int, int]:
    parts = callback_data.split(":")
    if len(parts) < 3:
        return 0, 0
    uid = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    return uid, page


def _pay_op_label(username: str) -> str:
    u = (username or "").strip() or "—"
    if len(u) > 40:
        u = u[:37] + "..."
    return f"Оплатить {u}"


async def _payout_ledger_text_and_markup(
    session: AsyncSession,
    *,
    page: int,
) -> tuple[str, InlineKeyboardMarkup]:
    rows, total = await BillingService(session=session).get_payouts_paginated(
        status=PayoutStatus.PENDING,
        page=page,
        page_size=LEDGER_PAGE_SIZE,
    )
    max_page = max((total - 1) // LEDGER_PAGE_SIZE, 0) if total > 0 else 0
    page = min(max(page, 0), max_page)

    lines = ["💰 ВЕДОМОСТЬ ВЫПЛАТ", ""]
    if not rows:
        lines.append("Нет пользователей с ожидающими выплатами.")
    else:
        for i, (payout, user) in enumerate(rows, start=page * LEDGER_PAGE_SIZE + 1):
            username = f"@{user.username}" if user.username else f"@{user.telegram_id}"
            lines.append(f"{i}. {username} | {payout.accepted_count} шт. | {payout.amount} USDT")
    text = "\n".join(lines)
    kb_rows: list[list[InlineKeyboardButton]] = []
    for payout, user in rows:
        uid = int(payout.user_id)
        username = f"@{user.username}" if user.username else f"@{user.telegram_id}"
        kb_rows.append(
            [InlineKeyboardButton(text=_pay_op_label(username), callback_data=f"{CB_PAY_MARK}:{uid}:{page}")]
        )
    if total > LEDGER_PAGE_SIZE:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="<<", callback_data=f"{CB_PAY_LEDGER_PAGE}:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP))
        if page < max_page:
            nav.append(InlineKeyboardButton(text=">>", callback_data=f"{CB_PAY_LEDGER_PAGE}:{page + 1}"))
        kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton(text="💳 Добавить USDT", callback_data=f"{CB_PAY_TOPUP}:{page}")])
    kb_rows.append(
        [
            InlineKeyboardButton(text="История выплат", callback_data=f"{CB_PAY_HISTORY_PAGE}:0"),
            InlineKeyboardButton(text="Корзина", callback_data=f"{CB_PAY_TRASH_PAGE}:0"),
        ]
    )
    kb_rows.append([InlineKeyboardButton(text="Управление PENDING", callback_data=f"{CB_PAY_PENDING_PAGE}:0")])
    kb_rows.append([InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)])
    return text, InlineKeyboardMarkup(inline_keyboard=kb_rows)


async def _edit_payout_ledger_message(message: Message, session: AsyncSession, *, page: int) -> None:
    text, kb = await _payout_ledger_text_and_markup(session, page=page)
    await edit_message_text_safe(message, text, reply_markup=kb)


async def _payout_history_text_and_markup(session: AsyncSession, *, page: int) -> tuple[str, InlineKeyboardMarkup]:
    page = max(page, 0)
    rows, total = await BillingService(session=session).get_payouts_paginated(
        status=PayoutStatus.PAID,
        page=page,
        page_size=PAGE_SIZE,
    )
    max_page = max((max(total, 1) - 1) // PAGE_SIZE, 0)
    if page > max_page:
        page = max_page
        rows, total = await BillingService(session=session).get_payouts_paginated(
            status=PayoutStatus.PAID,
            page=page,
            page_size=PAGE_SIZE,
        )
    lines = ["📜 История выплат", ""]
    if not rows:
        lines.append("Пока пусто.")
    else:
        for payout, user in rows:
            username = f"@{user.username}" if user.username else f"@{user.telegram_id}"
            lines.append(f"- {payout.period_key} | {username} | {payout.amount} USDT")
    text = "\n".join(lines)
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{CB_PAY_HISTORY_PAGE}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP))
    if page < max_page:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{CB_PAY_HISTORY_PAGE}:{page + 1}"))
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            nav,
            [InlineKeyboardButton(text="💰 К ведомости", callback_data=f"{CB_PAY_LEDGER_PAGE}:0")],
            [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)],
        ]
    )
    return text, kb


async def _payout_trash_text_and_markup(session: AsyncSession, *, page: int) -> tuple[str, InlineKeyboardMarkup]:
    page = max(page, 0)
    rows, total = await BillingService(session=session).get_payouts_paginated(
        status=PayoutStatus.CANCELLED,
        page=page,
        page_size=PAGE_SIZE,
    )
    max_page = max((max(total, 1) - 1) // PAGE_SIZE, 0)
    if page > max_page:
        page = max_page
        rows, total = await BillingService(session=session).get_payouts_paginated(
            status=PayoutStatus.CANCELLED,
            page=page,
            page_size=PAGE_SIZE,
        )
    lines = ["🗑 Корзина выплат", ""]
    if not rows:
        lines.append("Пока пусто.")
    else:
        for payout, user in rows:
            username = f"@{user.username}" if user.username else f"@{user.telegram_id}"
            lines.append(f"- {payout.period_key} | {username} | {payout.amount} USDT")
    text = "\n".join(lines)
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{CB_PAY_TRASH_PAGE}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP))
    if page < max_page:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{CB_PAY_TRASH_PAGE}:{page + 1}"))
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            nav,
            [InlineKeyboardButton(text="💰 К ведомости", callback_data=f"{CB_PAY_LEDGER_PAGE}:0")],
            [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)],
        ]
    )
    return text, kb


async def _payout_pending_manage_text_and_markup(
    session: AsyncSession,
    *,
    page: int,
) -> tuple[str, InlineKeyboardMarkup]:
    page = max(page, 0)
    rows, total = await BillingService(session=session).get_payouts_paginated(
        status=PayoutStatus.PENDING,
        page=page,
        page_size=PAGE_SIZE,
    )
    max_page = max((max(total, 1) - 1) // PAGE_SIZE, 0)
    if page > max_page:
        page = max_page
        rows, total = await BillingService(session=session).get_payouts_paginated(
            status=PayoutStatus.PENDING,
            page=page,
            page_size=PAGE_SIZE,
        )

    lines = ["⚙️ Управление PENDING выплатами", ""]
    kb_rows: list[list[InlineKeyboardButton]] = []

    if not rows:
        lines.append("PENDING выплат нет.")
    else:
        for payout, user in rows:
            username = f"@{user.username}" if user.username else f"@{user.telegram_id}"
            lines.append(
                f"#{payout.id} | {payout.period_key} | {username} | {payout.accepted_count} шт. | {payout.amount} USDT"
            )
            kb_rows.append(
                [InlineKeyboardButton(text=f"🗑 Удалить #{payout.id}", callback_data=f"{CB_PAY_PENDING_DELETE}:{payout.id}:{page}")]
            )

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{CB_PAY_PENDING_PAGE}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP))
    if page < max_page:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{CB_PAY_PENDING_PAGE}:{page + 1}"))
    kb_rows.append(nav)

    kb_rows.append([InlineKeyboardButton(text="💰 К ведомости", callback_data=f"{CB_PAY_LEDGER_PAGE}:0")])
    kb_rows.append([InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)])

    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb_rows)


def _parse_pay_topup_page(callback_data: str) -> int:
    parts = callback_data.split(":")
    if len(parts) < 3:
        return 0
    try:
        return max(int(parts[2]), 0)
    except ValueError:
        return 0


async def _admin_delete_prev_panel_message(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    old_id = data.get(_ADMIN_LAST_PANEL_MSG_KEY)
    if old_id is None or message.chat is None:
        return
    try:
        await message.bot.delete_message(chat_id=message.chat.id, message_id=int(old_id))
    except TelegramBadRequest:
        pass


async def _admin_store_panel_message(state: FSMContext, sent: Message | None) -> None:
    if sent is None:
        return
    await state.update_data(**{_ADMIN_LAST_PANEL_MSG_KEY: sent.message_id})


@router.message(Command("daily_report"))
async def on_daily_report(
    message: Message, state: FSMContext, session: AsyncSession, *, _caller_id: int | None = None
) -> None:
    """Показывает итоговую ведомость к выплате (одно сообщение)."""

    tid = _caller_id or (message.from_user.id if message.from_user else None)
    if tid is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.can_manage_payouts(tid):
        await message.answer("Недостаточно прав.")
        return

    text, kb = await _payout_ledger_text_and_markup(session, page=0)
    body = f"{HINT_PAYOUTS}\n\n{text}"
    data = await state.get_data()
    mid = data.get(_ADMIN_LAST_PANEL_MSG_KEY)
    if mid is not None and message.chat is not None:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=int(mid),
                text=body,
                reply_markup=kb,
            )
            return
        except TelegramBadRequest:
            pass

    await _admin_delete_prev_panel_message(message, state)
    sent = await message.answer(body, reply_markup=kb)
    await _admin_store_panel_message(state, sent)


@router.message(Command("export_report"))
async def on_export_report(message: Message, session: AsyncSession) -> None:
    """Экспортирует отчёт выплат в CSV/XLSX."""

    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    fmt = message.text.replace("/export_report", "", 1).strip().lower() or "csv"
    rows = await BillingService(session=session).get_daily_report_rows()
    if not rows:
        await message.answer("Нет данных для экспорта.")
        return

    if fmt == "xlsx":
        try:
            from openpyxl import Workbook
        except Exception:
            await message.answer("Для XLSX установи зависимость openpyxl.")
            return
        wb = Workbook()
        ws = wb.active
        ws.append(["username", "accepted_count", "to_pay"])
        for row in rows:
            ws.append([str(row["username"]), int(row["accepted_count"]), str(row["to_pay"])])
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        await message.answer_document(
            document=InputFile(buf, filename="daily_report.xlsx"),
            caption="Экспорт XLSX готов.",
        )
        return

    sio = StringIO()
    writer = csv.writer(sio)
    writer.writerow(["username", "accepted_count", "to_pay"])
    for row in rows:
        writer.writerow([row["username"], row["accepted_count"], row["to_pay"]])
    await message.answer_document(
        document=("daily_report.csv", sio.getvalue().encode("utf-8")),
        caption="CSV-файл подготовлен.",
    )


@router.callback_query(F.data.startswith(f"{CB_PAY_LEDGER_PAGE}:"))
async def on_payout_ledger_page(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    page = max(int(callback.data.rsplit(":", 1)[-1]), 0)
    await callback.answer()
    if callback.message is not None:
        await _edit_payout_ledger_message(callback.message, session, page=page)


@router.callback_query(
    lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_TOPUP}:") and len(c.data.split(":")) == 3
)
async def on_payout_topup_open(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    ledger_page = _parse_pay_topup_page(callback.data)
    await state.set_state(AdminPayoutState.waiting_for_topup_amount)
    await state.update_data(payout_topup_ledger_page=ledger_page)

    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            (
                "💳 <b>ПОПОЛНЕНИЕ APP БАЛАНСА</b>\n\n"
                "Введите сумму пополнения в USDT одним сообщением.\n"
                "Например: <code>1000</code> или <code>1000.50</code>."
            ),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ К ведомости", callback_data=f"{CB_PAY_LEDGER_PAGE}:{ledger_page}")],
                    [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)],
                ]
            ),
            parse_mode="HTML",
        )


@router.message(AdminPayoutState.waiting_for_topup_amount, F.text)
async def on_payout_topup_amount_entered(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if message.from_user is None:
        return
    if not await AdminService(session=session).can_manage_payouts(message.from_user.id):
        await state.clear()
        await message.answer("Недостаточно прав.")
        return

    raw = (message.text or "").strip().replace(",", ".")
    try:
        amount = Decimal(raw)
    except (InvalidOperation, TypeError):
        await message.answer("Некорректная сумма. Введите число, например: 1000 или 1000.50")
        return

    if amount <= Decimal("0"):
        await message.answer("Сумма должна быть больше 0.")
        return

    data = await state.get_data()
    ledger_page = int(data.get("payout_topup_ledger_page", 0))

    try:
        invoice = await CryptoBotService().create_topup_invoice(
            amount=amount,
            description=f"Manual top-up by admin {message.from_user.id}",
        )
    except RuntimeError as exc:
        await message.answer(f"Не удалось создать invoice: {exc}")
        return

    await state.clear()
    await message.answer(
        (
            "✅ <b>Invoice для пополнения создан</b>\n\n"
            f"<b>Сумма:</b> <code>{amount} USDT</code>\n"
            "\n"
            "После оплаты нажмите «✅ Я оплатил», бот проверит статус и вернёт в «Выплаты»."
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Я оплатил",
                        callback_data=f"{CB_PAY_TOPUP_CHECK}:{invoice.invoice_id}:{ledger_page}:{amount}",
                    )
                ],
                [InlineKeyboardButton(text="Открыть", url=invoice.invoice_url)],
            ]
        ),
    )


@router.callback_query(lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_TOPUP_CHECK}:"))
async def on_payout_topup_check_paid(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    parts = callback.data.split(":", 4)
    if len(parts) < 5:
        await callback.answer("Некорректные данные invoice", show_alert=True)
        return
    try:
        invoice_id = int(parts[2])
        ledger_page = max(int(parts[3]), 0)
    except ValueError:
        await callback.answer("Некорректный invoice id", show_alert=True)
        return
    amount_label = parts[4]

    try:
        status = await CryptoBotService().get_invoice_status(invoice_id)
    except RuntimeError as exc:
        await callback.answer(f"Ошибка проверки invoice: {exc}", show_alert=True)
        return

    if status.status != "paid":
        await callback.answer("Invoice ещё не оплачен", show_alert=True)
        return

    await callback.answer(f"✅ APP пополнен на {amount_label} USDT", show_alert=True)
    if callback.message is not None:
        await _edit_payout_ledger_message(callback.message, session, page=ledger_page)


@router.callback_query(lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_MARK}:"))
async def on_mark_paid(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if callback.from_user is None or callback.data is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    user_id, ledger_page = _parse_pay_uid_page(callback.data)
    if user_id <= 0:
        await callback.answer("Некорректные данные", show_alert=True)
        return
    user = await session.get(User, user_id)
    if user is None:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    pending_stmt = (
        select(Payout)
        .where(Payout.user_id == user_id, Payout.status == PayoutStatus.PENDING)
        .order_by(Payout.created_at.asc())
    )
    pending_payouts = list((await session.execute(pending_stmt)).scalars().all())

    if not pending_payouts:
        await callback.answer("Нет ожидающих выплат для этого пользователя", show_alert=True)
        return

    total_amount = Decimal("0.00")
    total_accepted_count = 0
    for payout in pending_payouts:
        total_amount += payout.amount
        total_accepted_count += payout.accepted_count

    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    rejected_stmt = select(func.count(Submission.id)).where(
        Submission.user_id == user_id,
        Submission.status.in_([
            SubmissionStatus.REJECTED,
            SubmissionStatus.BLOCKED,
            SubmissionStatus.NOT_A_SCAN,
        ]),
        Submission.reviewed_at >= day_start,
    )
    rejected_count = int((await session.execute(rejected_stmt)).scalar_one())

    await state.set_state(AdminPayoutState.waiting_for_payout_confirm)
    await state.update_data(
        payout_user_id=user_id,
        payout_total_amount=str(total_amount),
        payout_accepted_count=total_accepted_count,
        payout_rejected_count=rejected_count,
        payout_username=f"@{user.username}" if user.username else f"@{user.telegram_id}",
        payout_ledger_page=ledger_page,
    )

    await callback.answer()
    if callback.message is not None:
        username = f"@{user.username}" if user.username else f"@{user.telegram_id}"
        stats_text = (
            f"❖ <b>GDPX // ACADEMY</b> ─ Аудит\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>ПОДТВЕРЖДЕНИЕ ВЫПЛАТЫ</b> (Этап 1)\n\n"
            f"◾️ <b>Продавец:</b> {username}\n"
            f"◾️ <b>Период:</b> текущая сессия (UTC)\n\n"
            f"<b>СТАТИСТИКА:</b>\n"
            f"◾️ Принято к расчету: {total_accepted_count} шт.\n"
            f"▫️ Отклонено (брак): {rejected_count} шт.\n\n"
            f"<b>ИТОГОВАЯ СУММА:</b> {total_amount} USDT\n\n"
            f"<i>Внимание: Сумма сформирована согласно индивидуальным ставкам.</i>\n\n"
            f"<b>Инициировать транзакцию?</b>"
        )
        await edit_message_text_safe(
            callback.message,
            stats_text,
            reply_markup=payout_confirm_keyboard(user_id=user_id, ledger_page=ledger_page),
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_CANCEL}:"))
async def on_mark_paid_cancel(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if callback.data is None:
        return
    await state.clear()
    _user_id, ledger_page = _parse_pay_uid_page(callback.data)
    await callback.answer("Оплата отменена")
    if callback.message is not None:
        await _edit_payout_ledger_message(callback.message, session, page=ledger_page)


@router.callback_query(
    StateFilter(AdminPayoutState.waiting_for_payout_confirm),
    lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_CONFIRM}:")
)
async def on_payout_confirmation(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    if callback.from_user is None or callback.data is None:
        return

    data = await state.get_data()
    total_amount = data.get("payout_total_amount", "0.00")
    username = data.get("payout_username", "Unknown")
    try:
        payout_amount = Decimal(str(total_amount))
    except (InvalidOperation, TypeError):
        payout_amount = Decimal("0")

    available_usdt: Decimal | None = None
    balance_error: str | None = None
    try:
        available_usdt = await CryptoBotService().get_available_balance(asset_code="USDT")
    except RuntimeError as exc:
        balance_error = str(exc)

    if callback.message is not None:
        if balance_error is not None:
            balance_line = f"▫️ <b>Баланс CryptoPay:</b> ✕ ошибка доступа({escape(balance_error)})"
            warning_line = "✕ <i>Проверьте токен/доступность CryptoPay перед отправкой.</i>"
        else:
            assert available_usdt is not None
            balance_line = f"◾️ <b>Доступный резерв:</b> <code>{available_usdt} USDT</code>"
            warning_line = (
                "▫️ <i>Резерв исчерпан. Требуется пополнение.</i>"
                if available_usdt < payout_amount
                else "◾️ <i>Средств достаточно для исполнения транзакции.</i>"
            )

        final_text = (
            f"❖ <b>GDPX // ACADEMY</b> ─ Протокол\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>ФИНАЛЬНОЕ ПОДТВЕРЖДЕНИЕ</b> (Этап 2)\n\n"
            f"<b>Вы подтверждаете эмиссию чека?</b>\n\n"
            f"◾️ <b>К списанию:</b> <code>{total_amount} USDT</code>\n"
            f"◾️ <b>Получатель:</b> {username}\n"
            f"{balance_line}\n\n"
            f"{warning_line}\n"
            "✕ <i>Внимание: После фиксации чека операция становится необратимой.</i>"
        )

        user_id = data.get("payout_user_id")
        ledger_page = data.get("payout_ledger_page", 0)

        await callback.answer()
        await edit_message_text_safe(
            callback.message,
            final_text,
            reply_markup=payout_final_confirm_keyboard(user_id=user_id, ledger_page=ledger_page),
            parse_mode="HTML",
        )


@router.callback_query(
    StateFilter(AdminPayoutState.waiting_for_payout_confirm),
    lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_TOPUP}:")
)
async def on_create_topup_invoice(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.data is None or callback.message is None:
        return

    data = await state.get_data()
    total_amount = data.get("payout_total_amount", "0.00")
    username = data.get("payout_username", "Unknown")
    user_id = data.get("payout_user_id")
    ledger_page = int(data.get("payout_ledger_page", 0))

    if user_id is None:
        await callback.answer("Данные сессии потеряны", show_alert=True)
        return

    try:
        invoice_amount = Decimal(str(total_amount))
    except (InvalidOperation, TypeError):
        invoice_amount = Decimal("0")
    if invoice_amount <= Decimal("0"):
        invoice_amount = Decimal("1")

    try:
        await CryptoBotService().create_topup_invoice(
            amount=invoice_amount,
            description=f"Top-up for payout {username}",
        )
    except RuntimeError as exc:
        await callback.answer("Не удалось создать invoice", show_alert=True)
        await edit_message_text_safe(
            callback.message,
            f"▫️ Ошибка пополнения резерва:\n<code>{escape(str(exc))}</code>",
            reply_markup=payout_final_confirm_keyboard(user_id=user_id, ledger_page=ledger_page),
            parse_mode="HTML",
        )
        return

    await callback.answer("Инвойс сформирован")
    await edit_message_text_safe(
        callback.message,
        (
            "❖ <b>GDPX // ACADEMY</b> ─ Резерв\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>ПОПОЛНЕНИЕ ЛИКВИДНОСТИ</b>\n\n"
            f"◾️ <b>Сумма:</b> <code>{invoice_amount} USDT</code>\n"
            "\n"
            "После оплаты нажмите завершите эмиссию, нажав кнопку ниже."
        ),
        reply_markup=payout_final_confirm_keyboard(user_id=user_id, ledger_page=ledger_page),
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_TRASH}:"))
async def on_mark_trash(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await callback.answer("Админ не найден в БД", show_alert=True)
        return
    user_id, ledger_page = _parse_pay_uid_page(callback.data)
    payout = await BillingService(session=session).cancel_user_payout(
        user_id=user_id,
        cancelled_by_admin_id=admin_user.id,
    )
    if payout is None:
        await callback.answer("Баланс уже пустой или выплата обработана", show_alert=True)
        return
    await callback.answer("Перемещено в корзину")
    await AdminAuditService(session=session).log(
        admin_id=admin_user.id,
        action="cancel_payout",
        target_type="user",
        target_id=user_id,
        details=f"amount={payout.amount}",
    )
    if callback.message is not None:
        await _edit_payout_ledger_message(callback.message, session, page=ledger_page)


@router.callback_query(
    StateFilter(AdminPayoutState.waiting_for_payout_confirm),
    lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_FINAL_CONFIRM}:")
)
async def on_mark_paid_final(callback: CallbackQuery, session: AsyncSession, bot: Bot, state: FSMContext) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await callback.answer("Админ не найден в БД", show_alert=True)
        await state.clear()
        return

    data = await state.get_data()
    user_id = data.get("payout_user_id")
    total_amount_str = data.get("payout_total_amount", "0.00")
    ledger_page = data.get("payout_ledger_page", 0)

    if user_id is None:
        await callback.answer("Ошибка: данные сессии потеряны", show_alert=True)
        await state.clear()
        if callback.message is not None:
            await _edit_payout_ledger_message(callback.message, session, page=int(ledger_page))
        return

    user = await session.get(User, user_id)
    if user is None:
        await callback.answer("Пользователь не найден", show_alert=True)
        await state.clear()
        if callback.message is not None:
            await _edit_payout_ledger_message(callback.message, session, page=int(ledger_page))
        return

    amount = Decimal(total_amount_str)
    if amount <= Decimal("0.00"):
        await callback.answer("Баланс к выплате уже пустой", show_alert=True)
        await state.clear()
        if callback.message is not None:
            await _edit_payout_ledger_message(callback.message, session, page=int(ledger_page))
        return

    try:
        available_usdt = await CryptoBotService().get_available_balance(asset_code="USDT")
    except RuntimeError as exc:
        await callback.answer("Не удалось получить баланс CryptoPay", show_alert=True)
        if callback.message is not None:
            await edit_message_text_safe(
                callback.message,
                (
                    "▫️ <b>Ошибка проверки реального баланса CryptoPay</b>\n\n"
                    f"<code>{escape(str(exc))}</code>"
                ),
                reply_markup=payout_final_confirm_keyboard(user_id=user_id, ledger_page=ledger_page),
                parse_mode="HTML",
            )
        return

    if available_usdt < amount:
        await callback.answer("Недостаточно средств в CryptoPay", show_alert=True)
        if callback.message is not None:
            await edit_message_text_safe(
                callback.message,
                (
                    "▫️ <b>Недостаточно средств в CryptoPay</b>\n\n"
                    f"<b>Нужно:</b> <code>{amount} USDT</code>\n"
                    f"<b>Доступно:</b> <code>{available_usdt} USDT</code>\n\n"
                    "Нажмите «Пополнить через invoice», оплатите счёт и повторите отправку."
                ),
                reply_markup=payout_final_confirm_keyboard(user_id=user_id, ledger_page=ledger_page),
                parse_mode="HTML",
            )
        return

    username = f"@{user.username}" if user.username else f"@{user.telegram_id}"
    comment = f"Payment from @GDPX1 for {username}"

    try:
        check = await CryptoBotService().create_usdt_check(amount=amount, comment=comment)
    except RuntimeError as exc:
        error_msg = str(exc)
        if "NOT_ENOUGH_COINS" in error_msg:
            await callback.answer("Недостаточно средств на счёте CryptoBot", show_alert=True)
            if callback.message is not None:
                await edit_message_text_safe(
                    callback.message,
                    f"<b>▫️ Ошибка CryptoBot:</b>\n{error_msg}\n\n"
                    "<b>Решение:</b> Пополните баланс CryptoBot и повторите попытку.",
                    reply_markup=payout_final_confirm_keyboard(user_id=user_id, ledger_page=ledger_page),
                    parse_mode="HTML",
                )
            return

        await callback.answer("Не удалось создать чек CryptoBot", show_alert=True)
        if callback.message is not None:
            await edit_message_text_safe(
                callback.message,
                f"Ошибка CryptoBot: {exc}\n\nПопробуйте снова из ведомости.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="◾️ К ведомости",
                                callback_data=f"{CB_PAY_LEDGER_PAGE}:{int(ledger_page)}",
                            )
                        ]
                    ]
                ),
            )
        await state.clear()
        return

    payout = await BillingService(session=session).mark_user_paid_with_crypto(
        user_id=user_id,
        paid_by_admin_id=admin_user.id,
        crypto_check_id=check.check_id,
        crypto_check_url=check.check_url,
        note="cryptobot_check",
    )
    if payout is None:
        await callback.answer("◾️ Транзакция уже зафиксирована или баланс нулевой", show_alert=True)
        await state.clear()
        if callback.message is not None:
            await _edit_payout_ledger_message(callback.message, session, page=int(ledger_page))
        return

    await callback.answer("◾️ Транзакция исполнена!")
    await AdminAuditService(session=session).log(
        admin_id=admin_user.id,
        action="mark_paid",
        target_type="user",
        target_id=user_id,
        details=f"amount={payout.amount};check_id={check.check_id}",
    )

    await state.clear()

    if callback.message is not None:
        success_text = (
            "❖ <b>GDPX // ACADEMY</b> ─ Статус\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>ВЫПЛАТА УСПЕШНО ОТПРАВЛЕНА</b>\n\n"
            f"◾️ <b>Сумма:</b> {payout.amount} USDT\n"
            f"◾️ <b>Получатель:</b> {username}\n"
            f"◾️ <b>Активация:</b> <a href='{check.check_url}'>Открыть чек</a>\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Синхронизация реестра...</i>"
        )
        await edit_message_text_safe(
            callback.message,
            success_text,
            reply_markup=None,
            parse_mode="HTML",
        )
        await _edit_payout_ledger_message(callback.message, session, page=ledger_page)

    try:
        user_notification = (
            "❖ <b>GDPX // ACADEMY</b> ─ Финансы\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<b>ВАШ КАПИТАЛ ВЫПЛАЧЕН</b>\n\n"
            "Ваши активы успешно монетизированы. Благодарим за дисциплину поставок.\n\n"
            f"◾️ <b>Сумма:</b> <code>{payout.amount:.2f}</code> USDT\n"
            f"◾️ <b>Ваш чек:</b> <a href='{check.check_url}'>Получить выплату</a>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Реестр на текущую сессию закрыт.</i>"
        )
        await bot.send_message(user.telegram_id, user_notification, parse_mode="HTML")
    except TelegramAPIError:
        pass

    try:
        await bot.send_message(callback.from_user.id, f"Исполнено: <code>{payout.amount:.2f}</code> USDT {username}")
    except TelegramAPIError:
        pass


@router.callback_query(lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_HISTORY_PAGE}:"))
async def on_payout_history_page(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    page = max(int(callback.data.split(":")[2]), 0)
    text, kb = await _payout_history_text_and_markup(session, page=page)
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(callback.message, text, reply_markup=kb)


@router.callback_query(lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_TRASH_PAGE}:"))
async def on_payout_trash_page(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    page = max(int(callback.data.split(":")[2]), 0)
    text, kb = await _payout_trash_text_and_markup(session, page=page)
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(callback.message, text, reply_markup=kb)


@router.callback_query(lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_PENDING_PAGE}:"))
async def on_payout_pending_page(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    page = max(int(callback.data.split(":")[2]), 0)
    text, kb = await _payout_pending_manage_text_and_markup(session, page=page)
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(callback.message, text, reply_markup=kb)


@router.callback_query(lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_PENDING_DELETE}:"))
async def on_payout_pending_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    try:
        payout_id = int(parts[2])
        page = max(int(parts[3]), 0)
    except ValueError:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await callback.answer("Админ не найден", show_alert=True)
        return

    deleted = await BillingService(session=session).delete_pending_payout(payout_id=payout_id)
    if deleted is None:
        await callback.answer("PENDING выплата не найдена", show_alert=True)
    else:
        await AdminAuditService(session=session).log(
            admin_id=admin_user.id,
            action="delete_pending_payout",
            target_type="payout",
            target_id=int(deleted["payout_id"]),
            details=f"amount={deleted['amount']};user_id={deleted['user_id']}",
        )
        await callback.answer(f"Удалено: {deleted['amount']} USDT")

    text, kb = await _payout_pending_manage_text_and_markup(session, page=page)
    if callback.message is not None:
        await edit_message_text_safe(callback.message, text, reply_markup=kb)
