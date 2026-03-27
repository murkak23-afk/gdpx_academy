from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.enums import PayoutStatus
from src.database.models.submission import ReviewAction, Submission
from src.database.models.user import User
from src.handlers.admin_stats import send_stats_hub
from src.handlers.moderation import on_in_review_queue, on_moderation_queue
from src.keyboards import (
    BUTTON_ENTER_ADMIN_PANEL,
    BUTTON_EXIT_ADMIN_PANEL,
    CALLBACK_INLINE_BACK,
    REPLY_BTN_BACK,
    admin_main_menu_keyboard,
    is_admin_main_menu_text,
    match_admin_menu_canonical,
    pagination_keyboard,
    payout_confirm_keyboard,
    payout_mark_paid_keyboard,
    search_report_keyboard,
    seller_main_menu_keyboard,
)
from src.keyboards.admin_hints import (
    HINT_ADMIN_CATEGORIES,
    HINT_ARCHIVE,
    HINT_BROADCAST,
    HINT_PAYOUTS,
    HINT_REQUESTS,
)
from src.keyboards.callbacks import (
    CB_ADMIN_ARCHIVE_PAGE,
    CB_ADMIN_REPORT_SUBMISSION,
    CB_ADMIN_RESTRICT,
    CB_ADMIN_SEARCH_PAGE,
    CB_ADMIN_UNRESTRICT,
    CB_CAT,
    CB_CAT_PICK_CATEGORY,
    CB_CAT_PICK_CATEGORY_PAGE,
    CB_NOOP,
    CB_PAY_CANCEL,
    CB_PAY_CONFIRM,
    CB_PAY_HISTORY_PAGE,
    CB_PAY_MARK,
    CB_PAY_TRASH,
    CB_PAY_TRASH_PAGE,
    CB_REQ,
    CB_REQ_CLEAR,
    CB_REQ_CLEAR_CANCEL,
    CB_REQ_CLEAR_CONFIRM,
    CB_REQ_DELETE,
    CB_REQ_FACTORY_CANCEL,
    CB_REQ_FACTORY_CONFIRM,
    CB_REQ_FACTORY_RESET,
)
from src.services import (
    AdminAuditService,
    AdminService,
    ArchiveService,
    BillingService,
    CategoryService,
    CryptoBotService,
    SellerQuotaService,
    SubmissionService,
    UserService,
)
from src.states.admin_state import AdminBroadcastState, AdminCategoryState, AdminRequestsState
from src.states.moderation_state import AdminBatchPickState, AdminModerationForwardState
from src.utils.submission_media import message_answer_submission
from src.utils.text_format import edit_message_text_safe, non_empty_plain

router = Router(name="admin-router")
PHONE_QUERY_PATTERN = re.compile(r"^\+7\d{10}$")
PAGE_SIZE = 5
REQUESTS_MAX_CATEGORIES_DISPLAY = 60
CATEGORIES_PICK_PAGE_SIZE = 8


def _payout_sections_keyboard(history_page: int = 0, trash_page: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="История выплат",
                    callback_data=f"{CB_PAY_HISTORY_PAGE}:{history_page}",
                ),
                InlineKeyboardButton(
                    text="Корзина",
                    callback_data=f"{CB_PAY_TRASH_PAGE}:{trash_page}",
                ),
            ]
        ]
    )


def _admin_panel_intro_text() -> str:
    return (
        "Админ-панель.\n\n"
        "Команды:\n"
        "• /admin_categories — категории (подтипы операторов)\n"
        "• /admin — это меню\n\n"
        "Выход — кнопка «Выйти из админ панели»."
    )


def _reply_matches_menu_label(expected: str):
    """Совпадение текста reply-кнопки с учётом регистра и пробелов."""

    def _check(t: str | None) -> bool:
        return match_admin_menu_canonical(t) == expected

    return _check


_QUOTA_LINE_RE = re.compile(r"^\s*(\d+)\s+(\d+)\s+([0-9]+(?:[.,][0-9]{1,2})?)\s*$")
_QUOTA_DELETE_RE = re.compile(r"^\s*(\d+)\s*$")

async def _format_requests_page(
    session: AsyncSession,
    *,
    page: int,
) -> tuple[str, int]:
    categories = await CategoryService(session=session).get_active_categories()
    categories = categories[:REQUESTS_MAX_CATEGORIES_DISPLAY]

    today = datetime.now(timezone.utc).date()
    quota_svc = SellerQuotaService(session=session)

    quota_rows = await quota_svc.list_quotas_for_date(today)

    total = len(categories)
    max_page = max((total - 1) // PAGE_SIZE, 0)
    page = min(max(page, 0), max_page)
    start_idx = page * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    categories_page = categories[start_idx:end_idx]

    header = [
        "Ежедневные запросы (общие) по категориям",
        f"Дата (UTC): {today}",
        "Без привязки к продавцам",
        f"Страница: {page + 1}/{max_page + 1}",
    ]

    lines: list[str] = header + ["", "Категории (id — название):"]
    for c in categories_page:
        lines.append(f"  {c.id} — {c.title}")

    if not categories_page:
        lines.append("")
        lines.append("Активные категории не найдены.")
    lines.append("")
    lines.append("Заданные сегодня значения:")
    if not quota_rows:
        lines.append("  (пока пусто)")
    else:
        by_category: dict[int, tuple[int, Decimal, int]] = {}
        for row in quota_rows:
            cid = int(row.category_id)
            if cid in by_category:
                limit, price, cnt = by_category[cid]
                by_category[cid] = (limit, price, cnt + 1)
            else:
                by_category[cid] = (int(row.max_uploads), Decimal(row.unit_price), 1)
        for cid in sorted(by_category):
            limit, price, cnt = by_category[cid]
            lines.append(f"  category_id={cid} | лимит={limit} | цена={price} | продавцов={cnt}")

    lines.extend(
        [
            "",
            "Запрос задаётся строкой: category_id max_uploads unit_price_usdt",
            "Удаление одного: кнопка 🗑 → строка category_id",
            "Полная очистка: кнопка 🧹 (с подтверждением)",
            "Сброс до заводских: кнопка ♻️ (полная очистка всех дат)",
            "",
            HINT_REQUESTS,
        ]
    )
    return "\n".join(lines), total


def _requests_pagination_keyboard(*, page: int, total: int) -> InlineKeyboardMarkup:
    max_page = max((total - 1) // PAGE_SIZE, 0)
    page = min(max(page, 0), max_page)

    # "Разделы" клавиатуры: отдельно блок "Страницы" и отдельно блок "Поиск".
    arrows: list[InlineKeyboardButton] = []
    if page > 0:
        arrows.append(InlineKeyboardButton(text="⬅️", callback_data=f"{CB_REQ}:{page - 1}"))
    arrows.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP))
    if page < max_page:
        arrows.append(InlineKeyboardButton(text="➡️", callback_data=f"{CB_REQ}:{page + 1}"))

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Страницы", callback_data=CB_NOOP)],
            arrows,
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=CB_REQ_DELETE)],
            [InlineKeyboardButton(text="🧹 Очистить список", callback_data=CB_REQ_CLEAR)],
            [InlineKeyboardButton(text="♻️ Заводской сброс", callback_data=CB_REQ_FACTORY_RESET)],
            [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)],
        ]
    )


async def open_requests_section(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Раздел «Запросы»: ежедневные лимиты выгрузок для продавцов."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    page = 0
    text, total = await _format_requests_page(session, page=page)
    keyboard = _requests_pagination_keyboard(page=page, total=total)
    await state.set_state(AdminRequestsState.waiting_for_quota_line)
    await message.answer(non_empty_plain(text), reply_markup=keyboard)


_ADMIN_FSM_STATES = (
    AdminRequestsState.waiting_for_quota_line,
    AdminRequestsState.waiting_for_delete_line,
    AdminCategoryState.waiting_for_add_title,
    AdminCategoryState.waiting_for_add_payout_rate,
    AdminCategoryState.waiting_for_add_total_limit,
    AdminCategoryState.waiting_for_add_description,
    AdminCategoryState.waiting_for_add_photo,
    AdminCategoryState.waiting_for_pick_category,
    AdminCategoryState.waiting_for_edit_value,
    AdminBroadcastState.waiting_for_text,
    AdminModerationForwardState.waiting_for_target,
    AdminModerationForwardState.waiting_for_confirm,
    AdminBatchPickState.waiting_for_submission_ids,
    AdminBatchPickState.waiting_for_action,
)


@router.message(F.text == REPLY_BTN_BACK, StateFilter(*_ADMIN_FSM_STATES))
async def on_admin_fsm_step_back(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Шаг назад в админских сценариях или выход в главное меню."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        return

    st = await state.get_state()
    if st == AdminRequestsState.waiting_for_quota_line.state:
        await state.clear()
        await message.answer("Ввод запроса отменён.", reply_markup=admin_main_menu_keyboard())
        return
    if st == AdminRequestsState.waiting_for_delete_line.state:
        await state.clear()
        await message.answer("Удаление запроса отменено.", reply_markup=admin_main_menu_keyboard())
        return
    if st in (
        AdminCategoryState.waiting_for_add_title.state,
        AdminCategoryState.waiting_for_add_payout_rate.state,
        AdminCategoryState.waiting_for_add_total_limit.state,
        AdminCategoryState.waiting_for_add_description.state,
        AdminCategoryState.waiting_for_add_photo.state,
        AdminCategoryState.waiting_for_pick_category.state,
        AdminCategoryState.waiting_for_edit_value.state,
    ):
        await state.clear()
        await message.answer("Операция с категориями отменена.", reply_markup=admin_main_menu_keyboard())
        return
    if st == AdminBroadcastState.waiting_for_text.state:
        await state.clear()
        await message.answer("Рассылка отменена.", reply_markup=admin_main_menu_keyboard())
        return
    if st == AdminModerationForwardState.waiting_for_target.state:
        await state.clear()
        await message.answer("Пересылка отменена.", reply_markup=admin_main_menu_keyboard())
        return
    if st == AdminModerationForwardState.waiting_for_confirm.state:
        await state.clear()
        await message.answer("Пересылка отменена.", reply_markup=admin_main_menu_keyboard())
        return
    if st == AdminBatchPickState.waiting_for_submission_ids.state:
        await state.clear()
        await message.answer(
            "Выбор части пачки отменён. Снова открой «Очередь».",
            reply_markup=admin_main_menu_keyboard(),
        )
        return
    if st == AdminBatchPickState.waiting_for_action.state:
        await state.clear()
        await message.answer(
            "Действие для выбранной пачки отменено. Снова открой «Очередь».",
            reply_markup=admin_main_menu_keyboard(),
        )
        return


@router.message(F.text.func(_reply_matches_menu_label("Статистика")))
async def on_admin_stats_menu(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Сводки и отчёты."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).can_manage_payouts(message.from_user.id):
        raise SkipHandler()

    await state.clear()
    await send_stats_hub(message, session)


@router.callback_query(F.data == CB_NOOP)
async def on_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith(f"{CB_REQ}:"))
async def on_requests_ui(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """UI для раздела «Запросы»: пагинация и действия."""

    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return
    await callback.answer()

    if callback.message is None:
        return

    if callback.data == CB_REQ_DELETE:
        await callback.message.edit_reply_markup(reply_markup=None)
        await state.set_state(AdminRequestsState.waiting_for_delete_line)
        await callback.message.answer(
            "Удаление запроса: отправь `category_id`.\nПример: `12`",
            parse_mode="Markdown",
        )
        return
    if callback.data == CB_REQ_CLEAR:
        await callback.message.answer(
            "Очистить весь список запросов за сегодня (UTC)?",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Да, очистить", callback_data=CB_REQ_CLEAR_CONFIRM),
                        InlineKeyboardButton(text="❌ Отмена", callback_data=CB_REQ_CLEAR_CANCEL),
                    ]
                ]
            ),
        )
        return
    if callback.data == CB_REQ_CLEAR_CANCEL:
        await callback.answer("Очистка отменена")
        return
    if callback.data == CB_REQ_CLEAR_CONFIRM:
        today = datetime.now(timezone.utc).date()
        removed = await SellerQuotaService(session=session).clear_quotas_for_date(today)
        await callback.message.answer(f"Очищено записей: {removed}.")
        text, total = await _format_requests_page(session, page=0)
        keyboard = _requests_pagination_keyboard(page=0, total=total)
        await callback.message.answer(non_empty_plain(text), reply_markup=keyboard)
        await state.set_state(AdminRequestsState.waiting_for_quota_line)
        return
    if callback.data == CB_REQ_FACTORY_RESET:
        await callback.message.answer(
            "Сбросить `Запросы` до заводских настроек?\nЭто удалит все лимиты/цены по всем датам.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⚠️ Да, полный сброс",
                            callback_data=CB_REQ_FACTORY_CONFIRM,
                        ),
                        InlineKeyboardButton(text="❌ Отмена", callback_data=CB_REQ_FACTORY_CANCEL),
                    ]
                ]
            ),
        )
        return
    if callback.data == CB_REQ_FACTORY_CANCEL:
        await callback.answer("Сброс отменён")
        return
    if callback.data == CB_REQ_FACTORY_CONFIRM:
        removed_total = await SellerQuotaService(session=session).clear_all_quotas()
        await callback.message.answer(f"Заводской сброс выполнен. Удалено записей: {removed_total}.")
        text, total = await _format_requests_page(session, page=0)
        keyboard = _requests_pagination_keyboard(page=0, total=total)
        await callback.message.answer(non_empty_plain(text), reply_markup=keyboard)
        await state.set_state(AdminRequestsState.waiting_for_quota_line)
        return

    parts = callback.data.split(":", maxsplit=1)
    if len(parts) != 2:
        return
    _, page_s = parts
    try:
        page = int(page_s)
    except ValueError:
        page = 0

    text, total = await _format_requests_page(session, page=page)
    keyboard = _requests_pagination_keyboard(page=page, total=total)
    await edit_message_text_safe(callback.message, text, reply_markup=keyboard)


@router.message(AdminRequestsState.waiting_for_delete_line, F.text)
async def on_requests_delete_line(
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
    if raw.casefold() == "отмена" or raw == REPLY_BTN_BACK:
        await state.clear()
        await message.answer("Удаление отменено.", reply_markup=admin_main_menu_keyboard())
        return
    m = _QUOTA_DELETE_RE.match(raw)
    if not m:
        await message.answer("Нужна строка: category_id. Пример: 12")
        return
    category_id = int(m.group(1))
    category = await CategoryService(session=session).get_by_id(category_id)
    if category is None:
        await message.answer("Категория с таким id не найдена.")
        return
    today = datetime.now(timezone.utc).date()
    removed = await SellerQuotaService(session=session).clear_quotas_for_category_on_date(
        category_id,
        today,
    )
    if not removed:
        await message.answer("Запрос на сегодня не найден для этой категории.")
        return
    await state.set_state(AdminRequestsState.waiting_for_quota_line)
    text, total = await _format_requests_page(session, page=0)
    keyboard = _requests_pagination_keyboard(page=0, total=total)
    await message.answer(
        f"Удалено записей по категории {category_id} («{category.title}») за {today} UTC: {removed}.",
    )
    await message.answer(non_empty_plain(text), reply_markup=keyboard)


@router.message(F.text.func(is_admin_main_menu_text), StateFilter(*_ADMIN_FSM_STATES))
async def on_admin_menu_interrupt_fsm(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Сбрасывает админский FSM при нажатии кнопки меню и выполняет выбранный раздел."""

    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        return

    label = match_admin_menu_canonical(message.text)
    if label is None:
        return

    await state.clear()

    if label == "Очередь":
        await on_moderation_queue(message, session)
    elif label == "В работе":
        await on_in_review_queue(message, session)
    elif label == "Выплаты":
        await on_daily_report(message, session)
    elif label == "Запросы":
        await open_requests_section(message, state, session)
    elif label == "Рассылка":
        await on_broadcast_start(message, state, session)
    elif label == "Архив (7days)":
        await on_archive_help(message, session)
    elif label == "Статистика":
        await on_admin_stats_menu(message, state, session)


@router.message(F.text == BUTTON_ENTER_ADMIN_PANEL)
async def on_enter_admin_panel(message: Message, session: AsyncSession) -> None:
    """Открывает админ-панель (reply-меню админа)."""

    if message.from_user is None:
        return
    admin_service = AdminService(session=session)
    if not await admin_service.is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    await message.answer(_admin_panel_intro_text(), reply_markup=admin_main_menu_keyboard())


@router.message(F.text == BUTTON_EXIT_ADMIN_PANEL)
async def on_exit_admin_panel(message: Message, session: AsyncSession) -> None:
    """Возвращает обычное меню селлера + кнопку входа в админ-панель."""

    if message.from_user is None:
        return
    admin_service = AdminService(session=session)
    if not await admin_service.is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer("Пользователь не найден в БД.")
        return
    await message.answer(
        "Вы вышли из админ-панели. Профиль и сделки — в обычном меню ниже.",
        reply_markup=seller_main_menu_keyboard(language=user.language, role=user.role),
    )


@router.message(Command("admin"))
async def on_admin_panel(message: Message, session: AsyncSession) -> None:
    """Открывает главное меню админа."""

    if message.from_user is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    await message.answer(_admin_panel_intro_text(), reply_markup=admin_main_menu_keyboard())


def _admin_categories_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить", callback_data=f"{CB_CAT}:add")],
            [InlineKeyboardButton(text="⛔ Отключить", callback_data=f"{CB_CAT}:disable")],
            [InlineKeyboardButton(text="✅ Включить", callback_data=f"{CB_CAT}:enable")],
            [InlineKeyboardButton(text="🧮 Лимит категории", callback_data=f"{CB_CAT}:total")],
            [InlineKeyboardButton(text="💰 Payout rate", callback_data=f"{CB_CAT}:rate")],
            [InlineKeyboardButton(text="📝 Описание", callback_data=f"{CB_CAT}:desc")],
            [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)],
        ]
    )


def _admin_categories_picker_keyboard(*, categories: list, page: int) -> InlineKeyboardMarkup:
    """Инлайн-подбор категории без ввода category_id вручную."""

    total = len(categories)
    max_page = max((total - 1) // CATEGORIES_PICK_PAGE_SIZE, 0)
    page = min(max(page, 0), max_page)
    start = page * CATEGORIES_PICK_PAGE_SIZE
    end = start + CATEGORIES_PICK_PAGE_SIZE
    cats_page = categories[start:end]

    rows: list[list[InlineKeyboardButton]] = []
    for c in cats_page:
        state = "ACTIVE" if getattr(c, "is_active", False) else "DISABLED"
        total_limit = getattr(c, "total_upload_limit", None)
        total_limit_text = "∞" if total_limit is None else str(total_limit)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{c.id} — {c.title} | лимит: {total_limit_text} ({state})",
                    callback_data=f"{CB_CAT_PICK_CATEGORY}:{c.id}",
                )
            ]
        )

    # навигация по страницам
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{CB_CAT_PICK_CATEGORY_PAGE}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP))
    if page < max_page:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{CB_CAT_PICK_CATEGORY_PAGE}:{page + 1}"))
    rows.append(nav)

    rows.append([InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_admin_categories(session: AsyncSession) -> str:
    categories = await CategoryService(session=session).get_all_categories()
    if not categories:
        return "Категорий нет."

    lines: list[str] = ["Категории (id — название):"]
    for c in categories[:80]:
        state = "ACTIVE" if c.is_active else "DISABLED"
        total = "∞" if c.total_upload_limit is None else str(c.total_upload_limit)
        lines.append(f"{c.id}: {c.title} | {state} | rate={c.payout_rate} | total={total}")
    if len(categories) > 80:
        lines.append(f"… и ещё {len(categories) - 80} категорий")
    lines.append("")
    lines.append("Управляй категориями кнопками ниже.")
    return "\n".join(lines)


@router.message(Command("admin_categories"))
async def on_admin_categories_menu(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Меню управления категориями (подтипами операторов)."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    await state.clear()
    text = await _render_admin_categories(session)
    text = f"{text}\n\n{HINT_ADMIN_CATEGORIES}"
    await message.answer(non_empty_plain(text), reply_markup=_admin_categories_menu_keyboard())


@router.callback_query(F.data.startswith(f"{CB_CAT}:"))
async def on_admin_categories_actions(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Обработчик кнопок управления категориями."""

    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return
    await callback.answer()
    if callback.message is None:
        return

    action = callback.data.split(":", 1)[1]

    if action == "add":
        await state.clear()
        await state.set_state(AdminCategoryState.waiting_for_add_title)
        await edit_message_text_safe(
            callback.message,
            "Добавление категории.\nПришли название категории.\nПример: МТС(Салон)\nОтмена/«Назад» — кнопкой ⬅️ Назад.",
        )
        return

    if action in ("disable", "enable", "total", "rate", "desc"):
        await state.clear()
        await state.update_data(edit_action=action)
        await state.update_data(pick_page=0)
        await state.set_state(AdminCategoryState.waiting_for_pick_category)

        action_title = {
            "disable": "Отключить",
            "enable": "Включить",
            "total": "Изменить лимит категории",
            "rate": "Изменить payout rate",
            "desc": "Изменить описание",
        }.get(action, "Действие с категорией")

        categories = await CategoryService(session=session).get_all_categories()
        keyboard = _admin_categories_picker_keyboard(categories=categories, page=0)
        await edit_message_text_safe(
            callback.message,
            f"{action_title}.\nВыбери категорию кнопкой.",
            reply_markup=keyboard,
        )
        return

    if action.startswith("pick_page:"):
        if callback.message is None:
            return
        _, page_raw = action.split(":", 1)
        try:
            page = int(page_raw)
        except ValueError:
            page = 0
        await state.update_data(pick_page=page)
        categories = await CategoryService(session=session).get_all_categories()
        keyboard = _admin_categories_picker_keyboard(categories=categories, page=page)
        await callback.message.edit_reply_markup(reply_markup=keyboard)
        return

    if action.startswith("pick:"):
        if callback.message is None:
            return
        _, cat_id_raw = action.split(":", 1)
        try:
            category_id = int(cat_id_raw)
        except ValueError:
            await callback.answer("Некорректный category_id", show_alert=True)
            return

        data = await state.get_data()
        edit_action = data.get("edit_action")
        if not isinstance(edit_action, str):
            await state.clear()
            await callback.answer("Ошибка состояния. Начни заново.", show_alert=True)
            return

        if edit_action == "disable":
            await CategoryService(session=session).set_active(category_id=category_id, is_active=False)
            await state.clear()
            text = await _render_admin_categories(session)
            await edit_message_text_safe(
                callback.message,
                f"Категория отключена.\n\n{text}",
                reply_markup=_admin_categories_menu_keyboard(),
            )
            return

        if edit_action == "enable":
            await CategoryService(session=session).set_active(category_id=category_id, is_active=True)
            await state.clear()
            text = await _render_admin_categories(session)
            await edit_message_text_safe(
                callback.message,
                f"Категория включена.\n\n{text}",
                reply_markup=_admin_categories_menu_keyboard(),
            )
            return

        if edit_action not in {"total", "rate", "desc"}:
            await state.clear()
            await callback.answer("Неизвестное действие. Начни заново.", show_alert=True)
            return

        await state.update_data(edit_category_id=category_id)
        await state.set_state(AdminCategoryState.waiting_for_edit_value)

        if edit_action == "total":
            await edit_message_text_safe(
                callback.message,
                "Введите `total_upload_limit` (число) или '-' для без лимита.",
                reply_markup=None,
                parse_mode="Markdown",
            )
        elif edit_action == "rate":
            await edit_message_text_safe(
                callback.message,
                "Введите `payout_rate` (число, например 100.00).",
                reply_markup=None,
                parse_mode="Markdown",
            )
        else:
            await edit_message_text_safe(
                callback.message,
                "Введите новое описание. '-' — без описания.",
                reply_markup=None,
                parse_mode="Markdown",
            )
        return


def _parse_optional_int(raw: str) -> int | None | None:
    """Парсит целое число, а также 'none'/'-' -> None.

    Возвращает:
    - int,
    - None (значение 'без ограничений'),
    - или None как признак ошибки не используется (ошибка будет исключением).
    """

    v = raw.strip().casefold()
    if v in {"-", "none", "null", "без", "безлимит"}:
        return None
    return int(v)


def _parse_decimal(raw: str) -> Decimal:
    """Парсит Decimal, поддерживая запятую."""

    value = raw.strip().replace(",", ".")
    return Decimal(value)


@router.message(AdminCategoryState.waiting_for_add_title, F.text)
async def on_category_add_title(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.from_user is None or message.text is None:
        return

    raw = message.text.strip()
    if raw.casefold() == "отмена" or raw == REPLY_BTN_BACK:
        await state.clear()
        await message.answer("Добавление категории отменено.", reply_markup=admin_main_menu_keyboard())
        return
    if len(raw) < 2:
        await message.answer("Слишком короткое название. Попробуй ещё раз.")
        return

    await state.update_data(add_title=raw)
    await state.set_state(AdminCategoryState.waiting_for_add_payout_rate)
    await message.answer("Введите `payout_rate` (например: 100.00).", parse_mode="Markdown")


@router.message(AdminCategoryState.waiting_for_add_payout_rate, F.text)
async def on_category_add_payout_rate(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.from_user is None or message.text is None:
        return

    raw = message.text.strip()
    if raw.casefold() == "отмена" or raw == REPLY_BTN_BACK:
        await state.clear()
        await message.answer("Добавление категории отменено.", reply_markup=admin_main_menu_keyboard())
        return

    try:
        payout_rate = _parse_decimal(raw)
    except InvalidOperation:
        await message.answer("Неверный формат payout_rate. Пример: 100.00")
        return

    if payout_rate <= 0:
        await message.answer("payout_rate должен быть > 0.")
        return

    await state.update_data(add_payout_rate=payout_rate)
    await state.set_state(AdminCategoryState.waiting_for_add_total_limit)
    await message.answer("Введите `total_upload_limit` (целое число) или '-' для без лимита.")


@router.message(AdminCategoryState.waiting_for_add_total_limit, F.text)
async def on_category_add_total_limit(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.from_user is None or message.text is None:
        return

    raw = message.text.strip()
    if raw.casefold() == "отмена" or raw == REPLY_BTN_BACK:
        await state.clear()
        await message.answer("Добавление категории отменено.", reply_markup=admin_main_menu_keyboard())
        return

    try:
        total_limit = _parse_optional_int(raw)
    except ValueError:
        await message.answer("Неверный формат total_upload_limit. Пример: 50 или '-'.")
        return

    await state.update_data(add_total_limit=total_limit)
    await state.set_state(AdminCategoryState.waiting_for_add_description)
    await message.answer("Введите описание категории (или '-' чтобы без описания).")


@router.message(AdminCategoryState.waiting_for_add_description, F.text)
async def on_category_add_description(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.from_user is None or message.text is None:
        return

    raw = message.text.strip()
    if raw.casefold() == "отмена" or raw == REPLY_BTN_BACK:
        await state.clear()
        await message.answer("Добавление категории отменено.", reply_markup=admin_main_menu_keyboard())
        return

    description: str | None = None if raw.strip() == "-" else raw
    await state.update_data(add_description=description)
    await state.set_state(AdminCategoryState.waiting_for_add_photo)
    await message.answer("Отправь фото для категории или напиши 'пропустить'.", reply_markup=None)


@router.message(AdminCategoryState.waiting_for_add_photo, F.photo)
async def on_category_add_photo_photo(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.from_user is None or not message.photo:
        return

    data = await state.get_data()
    photo_file_id = message.photo[-1].file_id

    add_title = data.get("add_title")
    add_payout_rate = data.get("add_payout_rate")
    add_total_limit = data.get("add_total_limit")
    add_description = data.get("add_description")
    if add_title is None or add_payout_rate is None:
        await message.answer("Ошибка состояния. Начни добавление заново.")
        await state.clear()
        return

    await AdminService(session=session).create_category(
        title=str(add_title),
        payout_rate=add_payout_rate,
        description=add_description if add_description else None,
        photo_file_id=photo_file_id,
        total_upload_limit=add_total_limit,
    )
    await state.clear()
    await message.answer(
        "Категория добавлена.",
        reply_markup=None,
    )
    text = await _render_admin_categories(session)
    await message.answer(non_empty_plain(text), reply_markup=_admin_categories_menu_keyboard())


@router.message(AdminCategoryState.waiting_for_add_photo, F.text)
async def on_category_add_photo_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.from_user is None or message.text is None:
        return

    raw = message.text.strip()
    if raw == REPLY_BTN_BACK or raw.casefold() == "отмена":
        await state.clear()
        await message.answer("Добавление категории отменено.", reply_markup=admin_main_menu_keyboard())
        return

    if raw.casefold() in {"пропустить", "skip", "none", "-"}:
        data = await state.get_data()
        add_title = data.get("add_title")
        add_payout_rate = data.get("add_payout_rate")
        add_total_limit = data.get("add_total_limit")
        add_description = data.get("add_description")
        if add_title is None or add_payout_rate is None:
            await message.answer("Ошибка состояния. Начни добавление заново.")
            await state.clear()
            return

        await AdminService(session=session).create_category(
            title=str(add_title),
            payout_rate=add_payout_rate,
            description=add_description if add_description else None,
            photo_file_id=None,
            total_upload_limit=add_total_limit,
        )
        await state.clear()
        text = await _render_admin_categories(session)
        await message.answer("Категория добавлена (без фото).", reply_markup=None)
        await message.answer(non_empty_plain(text), reply_markup=_admin_categories_menu_keyboard())
        return

    await message.answer(
        "Похоже, это не фото и не команда. Напиши `пропустить` или отправь фото.",
        parse_mode="Markdown",
    )


@router.message(AdminCategoryState.waiting_for_edit_value, F.text)
async def on_category_edit_value(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.from_user is None or message.text is None:
        return

    raw = message.text.strip()
    if raw.casefold() == "отмена" or raw == REPLY_BTN_BACK:
        await state.clear()
        await message.answer("Редактирование отменено.", reply_markup=admin_main_menu_keyboard())
        return

    data = await state.get_data()
    edit_action = data.get("edit_action")
    category_id = data.get("edit_category_id")
    if not isinstance(edit_action, str) or not isinstance(category_id, int):
        await state.clear()
        await message.answer("Ошибка состояния. Начни заново.", reply_markup=_admin_categories_menu_keyboard())
        return

    if edit_action == "total":
        try:
            total_limit = _parse_optional_int(raw)
        except ValueError:
            await message.answer("Неверный формат total_upload_limit. Пример: 50 или '-'.")
            return
        await CategoryService(session=session).set_total_limit(category_id=category_id, total_limit=total_limit)

        pick_page = int(data.get("pick_page") or 0)
        # Возвращаем в меню выбора категории, чтобы можно было быстро поменять лимит на следующей.
        await state.set_state(AdminCategoryState.waiting_for_pick_category)
        categories = await CategoryService(session=session).get_all_categories()
        keyboard = _admin_categories_picker_keyboard(categories=categories, page=pick_page)
        await message.answer("Лимит обновлён. Выбери следующую категорию.", reply_markup=keyboard)
        return

    elif edit_action == "rate":
        try:
            payout_rate = _parse_decimal(raw)
        except InvalidOperation:
            await message.answer("Неверный формат payout_rate. Пример: 100.00")
            return
        if payout_rate <= 0:
            await message.answer("payout_rate должен быть > 0.")
            return
        await CategoryService(session=session).update_payout_rate(category_id=category_id, payout_rate=payout_rate)

    elif edit_action == "desc":
        description: str | None = None if raw == "-" else raw
        await CategoryService(session=session).update_description(category_id=category_id, description=description)

    else:
        await state.clear()
        await message.answer("Неизвестное действие. Начни заново.", reply_markup=_admin_categories_menu_keyboard())
        return

    await state.clear()
    text = await _render_admin_categories(session)
    await message.answer("Готово.", reply_markup=None)
    await message.answer(non_empty_plain(text), reply_markup=_admin_categories_menu_keyboard())


@router.message(F.text.func(_reply_matches_menu_label("Рассылка")))
async def on_broadcast_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Запускает массовую рассылку всем активным пользователям."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    await state.set_state(AdminBroadcastState.waiting_for_text)
    await message.answer(f"Отправь текст рассылки одним сообщением.\n\n{HINT_BROADCAST}")


@router.message(AdminBroadcastState.waiting_for_text)
async def on_broadcast_send(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: "Bot",
) -> None:
    """Отправляет массовую рассылку и показывает статистику доставки."""

    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await state.clear()
        await message.answer("Недостаточно прав.")
        return

    admin_user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    body = (message.text or "").strip()
    if not body:
        await message.answer("Текст рассылки не может быть пустым. Отправь непустой текст.")
        return

    recipients = await UserService(session=session).get_all_active_users()
    delivered = 0
    failed = 0
    for user in recipients:
        try:
            await bot.send_message(chat_id=user.telegram_id, text=body)
            delivered += 1
        except TelegramAPIError:
            failed += 1

    await state.clear()
    await message.answer(
        f"Рассылка завершена.\nУспешно: {delivered}\nОшибок: {failed}",
        reply_markup=admin_main_menu_keyboard(),
    )
    if admin_user is not None:
        await AdminAuditService(session=session).log(
            admin_id=admin_user.id,
            action="broadcast",
            target_type="users",
            details=f"delivered={delivered},failed={failed}",
        )


@router.message(F.text.func(_reply_matches_menu_label("Запросы")))
async def on_requests_menu(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Вход в раздел «Запросы» с главного меню."""

    await open_requests_section(message, state, session)


@router.message(AdminRequestsState.waiting_for_quota_line, F.text)
async def on_requests_quota_line(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Задаёт дневной запрос: лимит и цену за единицу."""

    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await state.clear()
        return
    raw = message.text.strip()
    if raw.casefold() == "отмена" or raw == REPLY_BTN_BACK:
        await state.clear()
        await message.answer("Выход.", reply_markup=admin_main_menu_keyboard())
        return
    m = _QUOTA_LINE_RE.match(raw)
    if not m:
        await message.answer("Нужна строка: id_категории лимит цена_USDT. Пример: 12 10 1.50")
        return
    category_id = int(m.group(1))
    limit = int(m.group(2))
    price_raw = m.group(3).replace(",", ".")
    try:
        unit_price = Decimal(price_raw)
    except InvalidOperation:
        await message.answer("Цена должна быть числом, например 1.50")
        return
    if limit < 0:
        await message.answer("Лимит не может быть отрицательным.")
        return
    if unit_price < Decimal("0"):
        await message.answer("Цена не может быть отрицательной.")
        return
    category = await CategoryService(session=session).get_by_id(category_id)
    if category is None or not category.is_active:
        await message.answer("Категория с таким id не найдена или неактивна.")
        return
    today = datetime.now(timezone.utc).date()
    sellers = await UserService(session=session).list_active_sellers()
    quota_svc = SellerQuotaService(session=session)
    for seller in sellers:
        await quota_svc.upsert_quota(
            seller.id,
            category_id,
            today,
            limit,
            unit_price=unit_price,
        )
    await state.clear()
    await message.answer(
        (
            f"На {today} (UTC) по категории «{category.title}» (id {category_id}) "
            f"задан общий запрос: лимит {limit}, цена {unit_price} USDT/шт.\n"
            f"Применено к продавцам: {len(sellers)}."
        ),
        reply_markup=admin_main_menu_keyboard(),
    )


@router.message(Command("daily_report"))
@router.message(F.text.func(_reply_matches_menu_label("Выплаты")))
async def on_daily_report(message: Message, session: AsyncSession) -> None:
    """Показывает итоговую ведомость к выплате."""

    if message.from_user is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.can_manage_payouts(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    rows = await BillingService(session=session).get_daily_report_rows()
    if not rows:
        await message.answer("Нет пользователей с балансом к выплате.")
        return

    first = True
    for row in rows:
        body = f"{row['username']} | {row['accepted_count']} accepted | To pay: {row['to_pay']} USDT"
        if first:
            body = f"{HINT_PAYOUTS}\n\n{body}"
            first = False
        await message.answer(
            text=body,
            reply_markup=payout_mark_paid_keyboard(user_id=int(row["user_id"])),
        )
    await message.answer("Разделы выплат:", reply_markup=_payout_sections_keyboard())


@router.message(F.text.func(_reply_matches_menu_label("Архив (7days)")))
async def on_archive_help(message: Message, session: AsyncSession) -> None:
    """Показывает, как искать номер в архиве за 7 дней."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).can_manage_payouts(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    await message.answer(
        "Поиск в архиве 7 дней:\n"
        "/archive 1234  (последние цифры)\n"
        "/archive +79999999999  (полный номер)\n\n"
        f"{HINT_ARCHIVE}",
        reply_markup=admin_main_menu_keyboard(),
    )


@router.message(Command("archive"))
async def on_archive_search(message: Message, session: AsyncSession) -> None:
    """Ищет номер в архиве товаров за 7 дней."""

    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    query = message.text.replace("/archive", "", 1).strip()
    if not query:
        await message.answer("Формат: /archive 1234 или /archive +79999999999")
        return

    archive_service = ArchiveService(session=session)
    await archive_service.prune_expired()
    rows, total = await archive_service.search_archive_by_phone_paginated(query=query, page=0, page_size=PAGE_SIZE)
    if not rows:
        await message.answer("В архиве за 7 дней ничего не найдено.")
        return

    for submission, seller in rows:
        seller_nickname = f"@{seller.username}" if seller.username else "без username"
        await message_answer_submission(
            message,
            submission,
            caption=(
                f"[Архив 7 дней] Submission #{submission.id}\n"
                f"Продавец: {seller_nickname}\n"
                f"Номер: {(submission.description_text or "").strip()}\n"
                f"Статус: {submission.status.value}"
            ),
            reply_markup=search_report_keyboard(submission_id=submission.id, seller_user_id=submission.user_id),
        )
    await message.answer(
        "Навигация архива:",
        reply_markup=pagination_keyboard(
            CB_ADMIN_ARCHIVE_PAGE,
            page=0,
            total=total,
            page_size=PAGE_SIZE,
            query=query,
        ),
    )


@router.callback_query(F.data.startswith(f"{CB_ADMIN_ARCHIVE_PAGE}:"))
async def on_archive_page(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    _, _, page_raw, query = callback.data.split(":", 3)
    page = max(int(page_raw), 0)
    archive_service = ArchiveService(session=session)
    rows, total = await archive_service.search_archive_by_phone_paginated(query=query, page=page, page_size=PAGE_SIZE)
    if callback.message is not None:
        for submission, seller in rows:
            seller_nickname = f"@{seller.username}" if seller.username else "без username"
            await message_answer_submission(
                callback.message,
                submission,
                caption=(
                    f"[Архив 7 дней] Submission #{submission.id}\n"
                    f"Продавец: {seller_nickname}\n"
                    f"Номер: {(submission.description_text or "").strip()}\n"
                    f"Статус: {submission.status.value}"
                ),
                reply_markup=search_report_keyboard(submission_id=submission.id, seller_user_id=submission.user_id),
            )
        await callback.message.answer(
            "Навигация архива:",
            reply_markup=pagination_keyboard(
                CB_ADMIN_ARCHIVE_PAGE,
                page=page,
                total=total,
                page_size=PAGE_SIZE,
                query=query,
            ),
        )
    await callback.answer()


@router.message(Command("s"))
async def on_search_submission(message: Message, session: AsyncSession) -> None:
    """Ищет товары в работе/истории по номеру или последним цифрам."""

    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    raw_query = message.text.replace("/s", "", 1).strip()
    if not raw_query:
        await message.answer("Формат: /s 1234 или /s +79999999999")
        return

    digits = re.sub(r"\D", "", raw_query)
    if not PHONE_QUERY_PATTERN.fullmatch(raw_query) and len(digits) < 3:
        await message.answer("Укажи минимум 3 последние цифры или полный номер.")
        return

    rows, total = await SubmissionService(session=session).search_by_phone_paginated(
        query=raw_query,
        page=0,
        page_size=PAGE_SIZE,
    )
    if not rows:
        await message.answer("Ничего не найдено по этому запросу.")
        return

    for submission, seller in rows:
        seller_nickname = f"@{seller.username}" if seller.username else "без username"
        await message_answer_submission(
            message,
            submission,
            caption=(
                f"Submission #{submission.id}\n"
                f"Продавец: {seller_nickname}\n"
                f"Номер: {(submission.description_text or "").strip()}\n"
                f"Статус: {submission.status.value}"
            ),
            reply_markup=search_report_keyboard(submission_id=submission.id, seller_user_id=submission.user_id),
        )
    await message.answer(
        "Навигация поиска:",
        reply_markup=pagination_keyboard(
            CB_ADMIN_SEARCH_PAGE,
            page=0,
            total=total,
            page_size=PAGE_SIZE,
            query=raw_query,
        ),
    )


@router.callback_query(F.data.startswith(f"{CB_ADMIN_SEARCH_PAGE}:"))
async def on_search_page(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    _, _, page_raw, query = callback.data.split(":", 3)
    page = max(int(page_raw), 0)
    rows, total = await SubmissionService(session=session).search_by_phone_paginated(
        query=query,
        page=page,
        page_size=PAGE_SIZE,
    )
    if callback.message is not None:
        for submission, seller in rows:
            seller_nickname = f"@{seller.username}" if seller.username else "без username"
            await message_answer_submission(
                callback.message,
                submission,
                caption=(
                    f"Submission #{submission.id}\n"
                    f"Продавец: {seller_nickname}\n"
                    f"Номер: {(submission.description_text or "").strip()}\n"
                    f"Статус: {submission.status.value}"
                ),
                reply_markup=search_report_keyboard(submission_id=submission.id, seller_user_id=submission.user_id),
            )
        await callback.message.answer(
            "Навигация поиска:",
            reply_markup=pagination_keyboard(
                CB_ADMIN_SEARCH_PAGE,
                page=page,
                total=total,
                page_size=PAGE_SIZE,
                query=query,
            ),
        )
    await callback.answer()


@router.callback_query(F.data.startswith(f"{CB_ADMIN_RESTRICT}:"))
async def on_restrict_user(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    admin = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin is None or not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    user_id = int(callback.data.split(":")[2])
    target = await UserService(session=session).set_restricted(user_id=user_id, value=True)
    if target is None:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    await AdminAuditService(session=session).log(
        admin_id=admin.id,
        action="set_restricted",
        target_type="user",
        target_id=user_id,
        details="manual from admin report",
    )
    await callback.answer("Ограничение включено")


@router.callback_query(F.data.startswith(f"{CB_ADMIN_UNRESTRICT}:"))
async def on_unrestrict_user(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    admin = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin is None or not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    user_id = int(callback.data.split(":")[2])
    target = await UserService(session=session).set_restricted(user_id=user_id, value=False)
    if target is None:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    await AdminAuditService(session=session).log(
        admin_id=admin.id,
        action="unset_restricted",
        target_type="user",
        target_id=user_id,
        details="manual from admin report",
    )
    await callback.answer("Ограничение снято")


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
            document=("daily_report.xlsx", buf.read()),
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
        caption="Экспорт CSV готов.",
    )


@router.callback_query(lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_MARK}:"))
async def on_mark_paid(callback: CallbackQuery, session: AsyncSession) -> None:
    """Запрашивает подтверждение выплаты пользователю."""

    if callback.from_user is None or callback.data is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    user_id = int(callback.data.split(":")[2])
    user = await session.get(User, user_id)
    if user is None:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    await callback.answer()
    if callback.message is not None:
        username = f"@{user.username}" if user.username else f"id:{user.telegram_id}"
        prev = non_empty_plain(callback.message.text or "")
        await edit_message_text_safe(
            callback.message,
            f"{prev}\n\n"
            f"Подтвердить выплату для {username}?\n"
            f"Сумма к выплате: {user.pending_balance} USDT",
            reply_markup=payout_confirm_keyboard(user_id=user_id),
        )


@router.callback_query(lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_CANCEL}:"))
async def on_mark_paid_cancel(callback: CallbackQuery) -> None:
    """Отменяет подтверждение выплаты."""

    await callback.answer("Оплата отменена")
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_TRASH}:"))
async def on_mark_trash(callback: CallbackQuery, session: AsyncSession) -> None:
    """Отправляет выплату в корзину (cancelled)."""

    if callback.from_user is None or callback.data is None:
        return
    admin_service = AdminService(session=session)
    if not await admin_service.can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await callback.answer("Админ не найден в БД", show_alert=True)
        return
    user_id = int(callback.data.split(":")[2])
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
        prev = non_empty_plain(callback.message.text or "")
        await edit_message_text_safe(
            callback.message,
            f"{prev}\n\nСтатус: в корзине ({payout.amount} USDT)",
        )


@router.callback_query(lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_CONFIRM}:"))
async def on_mark_paid_confirm(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    """Создает чек в CryptoBot и фиксирует выплату."""

    if callback.from_user is None or callback.data is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await callback.answer("Админ не найден в БД", show_alert=True)
        return

    user_id = int(callback.data.split(":")[2])
    user = await session.get(User, user_id)
    if user is None:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    amount = Decimal(user.pending_balance)
    if amount <= Decimal("0.00"):
        await callback.answer("Баланс к выплате уже пустой", show_alert=True)
        return

    username = f"@{user.username}" if user.username else f"id:{user.telegram_id}"
    comment = f"Payment from @GDPX1 for {username}"
    try:
        check = await CryptoBotService().create_usdt_check(amount=amount, comment=comment)
    except RuntimeError as exc:
        await callback.answer("Не удалось создать чек CryptoBot", show_alert=True)
        if callback.message is not None:
            await callback.message.answer(f"Ошибка CryptoBot: {exc}")
        return

    payout = await BillingService(session=session).mark_user_paid_with_crypto(
        user_id=user_id,
        paid_by_admin_id=admin_user.id,
        crypto_check_id=check.check_id,
        crypto_check_url=check.check_url,
        note="cryptobot_check",
    )
    if payout is None:
        await callback.answer("Выплата уже зафиксирована или баланс нулевой", show_alert=True)
        return

    await callback.answer("Выплата зафиксирована")
    await AdminAuditService(session=session).log(
        admin_id=admin_user.id,
        action="mark_paid",
        target_type="user",
        target_id=user_id,
        details=f"amount={payout.amount};check_id={check.check_id}",
    )
    if callback.message is not None:
        prev = non_empty_plain(callback.message.text or "")
        await edit_message_text_safe(
            callback.message,
            f"{prev}\n\nСтатус: выплачено ({payout.amount} USDT)\nЧек: {check.check_url}",
        )
    try:
        await bot.send_message(
            user.telegram_id,
            f"Выплата сформирована.\nСумма: {payout.amount} USDT\nПолучить чек: {check.check_url}",
        )
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
    rows, total = await BillingService(session=session).get_payouts_paginated(
        status=PayoutStatus.PAID,
        page=page,
        page_size=PAGE_SIZE,
    )
    if callback.message is not None:
        if not rows:
            await callback.message.answer("История выплат пока пустая.")
        else:
            lines: list[str] = ["История выплат:"]
            for payout, user in rows:
                username = f"@{user.username}" if user.username else f"id:{user.telegram_id}"
                lines.append(f"- {payout.period_key} | {username} | {payout.amount} USDT")
            await callback.message.answer(
                "\n".join(lines),
                reply_markup=pagination_keyboard(
                    CB_PAY_HISTORY_PAGE,
                    page=page,
                    total=total,
                    page_size=PAGE_SIZE,
                ),
            )
    await callback.answer()


@router.callback_query(lambda c: c.data is not None and c.data.startswith(f"{CB_PAY_TRASH_PAGE}:"))
async def on_payout_trash_page(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).can_manage_payouts(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    page = max(int(callback.data.split(":")[2]), 0)
    rows, total = await BillingService(session=session).get_payouts_paginated(
        status=PayoutStatus.CANCELLED,
        page=page,
        page_size=PAGE_SIZE,
    )
    if callback.message is not None:
        if not rows:
            await callback.message.answer("Корзина выплат пока пустая.")
        else:
            lines: list[str] = ["Корзина выплат:"]
            for payout, user in rows:
                username = f"@{user.username}" if user.username else f"id:{user.telegram_id}"
                lines.append(f"- {payout.period_key} | {username} | {payout.amount} USDT")
            await callback.message.answer(
                "\n".join(lines),
                reply_markup=pagination_keyboard(
                    CB_PAY_TRASH_PAGE,
                    page=page,
                    total=total,
                    page_size=PAGE_SIZE,
                ),
            )
    await callback.answer()


@router.callback_query(F.data.startswith(f"{CB_ADMIN_REPORT_SUBMISSION}:"))
async def on_submission_report(callback: CallbackQuery, session: AsyncSession) -> None:
    """Показывает детальный отчет по выбранному товару."""

    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    submission_id = int(callback.data.split(":")[2])
    submission = await session.get(Submission, submission_id)
    if submission is None:
        await callback.answer("Товар не найден", show_alert=True)
        return

    seller = await session.get(User, submission.user_id)
    seller_nickname = f"@{seller.username}" if seller is not None and seller.username else "без username"

    actions_stmt = (
        select(ReviewAction).where(ReviewAction.submission_id == submission.id).order_by(ReviewAction.created_at.asc())
    )
    actions = list((await session.execute(actions_stmt)).scalars().all())
    history_lines = [
        f"- {action.created_at}: "
        f"{action.from_status.value if action.from_status else 'none'} -> {action.to_status.value}"
        for action in actions
    ]
    history_text = "\n".join(history_lines) if history_lines else "- без изменений статуса"

    number_line = non_empty_plain((submission.description_text or "").strip(), placeholder="—")
    report_text = (
        f"Отчёт по товару #{submission.id}\n"
        f"Продавец: {seller_nickname}\n"
        f"Номер: {number_line}\n"
        f"Текущий статус: {submission.status.value}\n"
        f"Создано: {submission.created_at}\n"
        f"Взято в работу: {submission.assigned_at}\n"
        f"Проверено: {submission.reviewed_at}\n"
        f"Начислено: {submission.accepted_amount}\n\n"
        "История статусов:\n"
        f"{history_text}"
    )
    await callback.answer()
    await callback.message.answer(non_empty_plain(report_text))  # type: ignore[union-attr]
