from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
import re

from aiogram.exceptions import TelegramAPIError
from aiogram import Bot, Router
from aiogram import F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.submission import ReviewAction, Submission
from src.database.models.user import User
from src.database.models.enums import SubmissionStatus, UserRole
from src.keyboards import (
    ADMIN_MAIN_MENU_TEXTS,
    BUTTON_ENTER_ADMIN_PANEL,
    BUTTON_EXIT_ADMIN_PANEL,
    CALLBACK_INLINE_BACK,
    REPLY_BTN_BACK,
    admin_main_menu_keyboard,
    is_admin_main_menu_text,
    match_admin_menu_canonical,
    pagination_keyboard,
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
from src.services import (
    AdminAuditService,
    AdminService,
    ArchiveService,
    BillingService,
    CategoryService,
    SellerQuotaService,
    SubmissionService,
    UserService,
)
from src.states import (
    AdminCategoryState,
    AdminBatchPickState,
    AdminBroadcastState,
    AdminModerationForwardState,
    AdminRequestsState,
)
from src.handlers.admin_stats import send_stats_hub
from src.handlers.moderation import on_in_review_queue, on_moderation_queue
from src.utils.submission_media import bot_send_submission, message_answer_submission

router = Router(name="admin-router")
PHONE_QUERY_PATTERN = re.compile(r"^\+7\d{10}$")
PAGE_SIZE = 5
REQUESTS_MAX_CATEGORIES_DISPLAY = 60

def _admin_panel_intro_text() -> str:
    return (
        "Админ-панель.\n\n"
        "Команды:\n"
        "• /admin_categories — категории (подтипы операторов)\n"
        "• /admin — это меню\n\n"
        "Выход — кнопка «Выйти из админ панели»."
    )

# Кнопки главного меню админа (см. keyboards.constants.ADMIN_MAIN_MENU_TEXTS)
_ADMIN_MENU_TEXTS = ADMIN_MAIN_MENU_TEXTS

def _reply_matches_menu_label(expected: str):
    """Совпадение текста reply-кнопки с учётом регистра и пробелов."""

    def _check(t: str | None) -> bool:
        return match_admin_menu_canonical(t) == expected

    return _check


_QUOTA_LINE_RE = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\d+)\s*$")
_REQUESTS_ID_RE = re.compile(r"^\d{5,20}$")
_REQUESTS_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,32}$")

_TELEGRAM_TEXT_CHUNK = 3900


def _split_telegram_chunks(text: str, max_len: int = _TELEGRAM_TEXT_CHUNK) -> list[str]:
    if len(text) <= max_len:
        return [text]
    lines = text.split("\n")
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for line in lines:
        sep = 1 if cur else 0
        need = sep + len(line)
        if cur_len + need > max_len and cur:
            chunks.append("\n".join(cur))
            cur = [line]
            cur_len = len(line)
        else:
            cur_len += need
            cur.append(line)
    if cur:
        chunks.append("\n".join(cur))
    return chunks


async def _format_requests_dashboard(session: AsyncSession) -> str:
    users = await UserService(session=session).list_active_sellers()
    categories = await CategoryService(session=session).get_active_categories()
    today = datetime.now(timezone.utc).date()
    quota_svc = SellerQuotaService(session=session)
    sub_svc = SubmissionService(session=session)
    quota_rows = await quota_svc.list_quotas_for_date(today)
    quota_map: dict[tuple[int, int], int] = {}
    for r in quota_rows:
        quota_map[(r.user_id, r.category_id)] = r.max_uploads

    lines: list[str] = [
        "Лимиты «запроса» задаются отдельно для каждой категории (подтип оператора), UTC-сутки.",
        "",
        f"Дата: {today}",
        "",
        "Категории (id — название):",
    ]
    if not categories:
        lines.append("  (нет активных категорий)")
    else:
        for c in categories[:300]:
            lines.append(f"  {c.id} — {c.title}")
        if len(categories) > 300:
            lines.append(f"  … ещё {len(categories) - 300}.")
    lines.append("")
    if not users:
        lines.append("Продавцов в базе нет.")
    else:
        lines.append("По каждому продавцу: для каждого id категории — запрос/сегодня (сколько уже выгружено).")
        lines.append("")
        for u in users[:200]:
            un = f"@{u.username}" if u.username else "—"
            lines.append(f"— tg {u.telegram_id} | {un}")
            counts = await sub_svc.get_daily_counts_by_category_for_user(u.id)
            parts: list[str] = []
            for c in categories:
                q = quota_map.get((u.id, c.id), 0)
                used = counts.get(c.id, 0)
                parts.append(f"{c.id}:{q}/{used}")
            # несколько строк по ширине, чтобы не раздувать одну строку
            line_buf: list[str] = []
            line_len = 0
            for p in parts:
                add = len(p) + (2 if line_buf else 0)
                if line_len + add > 90 and line_buf:
                    lines.append("  " + "  ".join(line_buf))
                    line_buf = [p]
                    line_len = len(p)
                else:
                    if line_buf:
                        line_len += 2
                    line_buf.append(p)
                    line_len += len(p)
            if line_buf:
                lines.append("  " + "  ".join(line_buf))
        if len(users) > 200:
            lines.append(f"\n… и ещё {len(users) - 200} продавцов.")
    lines.extend(
        [
            "",
            "Отправь одной строкой: telegram_id id_категории лимит (целые числа, лимит ≥ 0).",
            "Пример: 123456789 12 25",
        ]
    )
    return "\n".join(lines)


def _sanitize_requests_query(raw: str) -> str | None:
    """Нормализует запрос поиска: '@nick' -> 'nick', числовой ID -> '123...'."""

    if not raw:
        return None
    q = raw.strip()
    if q.startswith("@"):
        q = q[1:]
    q = q.strip()
    if not q:
        return None
    if _REQUESTS_ID_RE.match(q):
        return q
    if _REQUESTS_USERNAME_RE.match(q):
        return q
    return None


async def _list_sellers_page(
    session: AsyncSession,
    *,
    page: int,
    query: str,
    page_size: int,
) -> tuple[int, list[User]]:
    """Возвращает (total_count, sellers_for_page)."""

    base_filters = [
        User.is_active.is_(True),
        User.role.in_((UserRole.SELLER, UserRole.CHIEF_ADMIN)),
    ]

    if query and _REQUESTS_ID_RE.match(query):
        base_filters.append(User.telegram_id == int(query))
    elif query:
        base_filters.append(User.username.ilike(f"%{query}%"))

    total_stmt = select(func.count(User.id)).where(*base_filters)
    total = int((await session.execute(total_stmt)).scalar_one())

    if page < 0:
        page = 0
    max_page = max((total - 1) // page_size, 0)
    page = min(page, max_page)

    stmt = (
        select(User)
        .where(*base_filters)
        .order_by(User.id.asc())
        .limit(page_size)
        .offset(page * page_size)
    )
    sellers = list((await session.execute(stmt)).scalars().all())
    return total, sellers


async def _format_requests_page(
    session: AsyncSession,
    *,
    query: str,
    page: int,
) -> tuple[str, int]:
    categories = await CategoryService(session=session).get_active_categories()
    categories = categories[:REQUESTS_MAX_CATEGORIES_DISPLAY]

    today = datetime.now(timezone.utc).date()
    quota_svc = SellerQuotaService(session=session)
    sub_svc = SubmissionService(session=session)

    quota_rows = await quota_svc.list_quotas_for_date(today)
    quota_map: dict[tuple[int, int], int] = {(r.user_id, r.category_id): int(r.max_uploads) for r in quota_rows}

    total, sellers = await _list_sellers_page(
        session,
        page=page,
        query=query,
        page_size=PAGE_SIZE,
    )

    max_page = max((total - 1) // PAGE_SIZE, 0)
    page = min(max(page, 0), max_page)

    header = [
        "Ежедневные запросы (квоты) по категориям",
        f"Дата (UTC): {today}",
        f"Поиск: {('—' if not query else query)}",
        f"Страница: {page + 1}/{max_page + 1}",
    ]

    lines: list[str] = header + ["", "Категории (id — название):"]
    for c in categories:
        lines.append(f"  {c.id} — {c.title}")

    if not sellers:
        lines.append("")
        lines.append("Ничего не найдено по текущему поиску.")
    else:
        lines.append("")
        for u in sellers:
            un = f"@{u.username}" if u.username else "—"
            lines.append(f"tg {u.telegram_id} | {un}")
            counts = await sub_svc.get_daily_counts_by_category_for_user(u.id)
            parts: list[str] = []
            for c in categories:
                q = quota_map.get((u.id, c.id), 0)
                used = counts.get(c.id, 0)
                parts.append(f"{c.id}:{q}/{used}")
            lines.append("  " + "  ".join(parts))

    lines.extend(
        [
            "",
            "Квота задаётся строкой: telegram_id category_id max_uploads",
            "Поиск: кнопка 🔎 → отправь @nickname или telegram_id.",
            "",
            HINT_REQUESTS,
        ]
    )
    return "\n".join(lines), total


def _requests_pagination_keyboard(*, page: int, total: int, query: str) -> InlineKeyboardMarkup:
    query_safe = query or ""
    max_page = max((total - 1) // PAGE_SIZE, 0)
    page = min(max(page, 0), max_page)

    # "Разделы" клавиатуры: отдельно блок "Страницы" и отдельно блок "Поиск".
    arrows: list[InlineKeyboardButton] = []
    if page > 0:
        arrows.append(InlineKeyboardButton(text="⬅️", callback_data=f"req:{page - 1}:{query_safe}"))
    arrows.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data="noop"))
    if page < max_page:
        arrows.append(InlineKeyboardButton(text="➡️", callback_data=f"req:{page + 1}:{query_safe}"))

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Страницы", callback_data="noop")],
            arrows,
            [InlineKeyboardButton(text="🔎 Поиск", callback_data="req:search")],
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
    query = ""
    page = 0
    text, total = await _format_requests_page(session, query=query, page=page)
    keyboard = _requests_pagination_keyboard(page=page, total=total, query=query)
    await state.set_state(AdminRequestsState.waiting_for_quota_line)
    await message.answer(text, reply_markup=keyboard)


_ADMIN_FSM_STATES = (
    AdminRequestsState.waiting_for_quota_line,
    AdminRequestsState.waiting_for_search_query,
    AdminCategoryState.waiting_for_add_title,
    AdminCategoryState.waiting_for_add_payout_rate,
    AdminCategoryState.waiting_for_add_total_limit,
    AdminCategoryState.waiting_for_add_description,
    AdminCategoryState.waiting_for_add_photo,
    AdminCategoryState.waiting_for_edit_id,
    AdminCategoryState.waiting_for_edit_value,
    AdminBroadcastState.waiting_for_text,
    AdminModerationForwardState.waiting_for_target,
    AdminBatchPickState.waiting_for_submission_ids,
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
    if st == AdminRequestsState.waiting_for_search_query.state:
        await state.clear()
        await message.answer("Поиск отменён.", reply_markup=admin_main_menu_keyboard())
        return
    if st in (
        AdminCategoryState.waiting_for_add_title.state,
        AdminCategoryState.waiting_for_add_payout_rate.state,
        AdminCategoryState.waiting_for_add_total_limit.state,
        AdminCategoryState.waiting_for_add_description.state,
        AdminCategoryState.waiting_for_add_photo.state,
        AdminCategoryState.waiting_for_edit_id.state,
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
    if st == AdminBatchPickState.waiting_for_submission_ids.state:
        await state.clear()
        await message.answer(
            "Выбор части пачки отменён. Снова открой «Очередь».",
            reply_markup=admin_main_menu_keyboard(),
        )
        return


@router.message(F.text.func(_reply_matches_menu_label("Статистика")))
async def on_admin_stats_menu(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Сводки и отчёты."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    await state.clear()
    await send_stats_hub(message, session)


@router.callback_query(F.data == "noop")
async def on_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("req:"))
async def on_requests_ui(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """UI для раздела «Запросы»: пагинация и поиск."""

    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return
    await callback.answer()

    if callback.message is None:
        return

    if callback.data == "req:search":
        # Закрываем часть клавиатуры (убираем inline-меню), чтобы пользователь вводил текст.
        await callback.message.edit_reply_markup(reply_markup=None)
        await state.set_state(AdminRequestsState.waiting_for_search_query)
        await callback.message.answer(
            "Поиск продавца: отправь `@nickname` или `telegram_id`.\nПример: @some_name или 123456789",
            parse_mode="Markdown",
        )
        return

    parts = callback.data.split(":", maxsplit=2)
    if len(parts) != 3:
        return
    _, page_s, query_s = parts
    try:
        page = int(page_s)
    except ValueError:
        page = 0
    query = query_s or ""

    text, total = await _format_requests_page(session, query=query, page=page)
    keyboard = _requests_pagination_keyboard(page=page, total=total, query=query)
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.message(AdminRequestsState.waiting_for_search_query, F.text)
async def on_requests_search_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Получает @nickname или telegram_id и перерисовывает страницу результатов."""

    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await state.clear()
        return

    q = _sanitize_requests_query(message.text)
    if q is None:
        await message.answer(
            "Неверный формат поиска.\nНужен `@nickname` (латиница/цифры/_) или `telegram_id` (число).",
            parse_mode="Markdown",
        )
        return

    # Возвращаем режим ввода лимитов (строками) после показа результатов.
    await state.set_state(AdminRequestsState.waiting_for_quota_line)

    page = 0
    text, total = await _format_requests_page(session, query=q, page=page)
    keyboard = _requests_pagination_keyboard(page=page, total=total, query=q)
    await message.answer(text, reply_markup=keyboard)


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
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    await message.answer(_admin_panel_intro_text(), reply_markup=admin_main_menu_keyboard())


@router.message(F.text == BUTTON_EXIT_ADMIN_PANEL)
async def on_exit_admin_panel(message: Message, session: AsyncSession) -> None:
    """Возвращает обычное меню селлера + кнопку входа в админ-панель."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
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
            [InlineKeyboardButton(text="➕ Добавить", callback_data="cat:add")],
            [InlineKeyboardButton(text="⛔ Отключить", callback_data="cat:disable")],
            [InlineKeyboardButton(text="✅ Включить", callback_data="cat:enable")],
            [InlineKeyboardButton(text="🧮 Лимит категории", callback_data="cat:total")],
            [InlineKeyboardButton(text="💰 Payout rate", callback_data="cat:rate")],
            [InlineKeyboardButton(text="📝 Описание", callback_data="cat:desc")],
            [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)],
        ]
    )


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
    await message.answer(text, reply_markup=_admin_categories_menu_keyboard())


@router.callback_query(F.data.startswith("cat:"))
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
        await callback.message.edit_text(
            "Добавление категории.\nПришли название категории.\nПример: МТС(Салон)\nОтмена/«Назад» — кнопкой ⬅️ Назад.",
        )
        return

    if action in ("disable", "enable", "total", "rate", "desc"):
        await state.clear()
        await state.update_data(edit_action=action)
        await state.set_state(AdminCategoryState.waiting_for_edit_id)
        await callback.message.edit_text(
            "Редактирование категории.\nПришли `category_id` (число).\nОтмена/«Назад» — кнопкой ⬅️ Назад.",
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
    await message.answer(text, reply_markup=_admin_categories_menu_keyboard())


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
        await message.answer(text, reply_markup=_admin_categories_menu_keyboard())
        return

    await message.answer("Похоже, это не фото и не команда. Напиши `пропустить` или отправь фото.", parse_mode="Markdown")


@router.message(AdminCategoryState.waiting_for_edit_id, F.text)
async def on_category_edit_id(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await state.clear()
        await message.answer("Недостаточно прав.")
        return

    raw = message.text.strip()
    if raw.casefold() == "отмена" or raw == REPLY_BTN_BACK:
        await state.clear()
        await message.answer("Редактирование отменено.", reply_markup=_admin_categories_menu_keyboard())
        return

    try:
        category_id = int(raw)
    except ValueError:
        await message.answer("Нужно число: category_id.")
        return

    data = await state.get_data()
    edit_action = data.get("edit_action")
    if not isinstance(edit_action, str):
        await state.clear()
        await message.answer("Ошибка состояния. Начни заново.", reply_markup=_admin_categories_menu_keyboard())
        return

    cat = await CategoryService(session=session).get_by_id(category_id)
    if cat is None:
        await message.answer("Категория с таким id не найдена.")
        return

    if edit_action == "disable":
        await CategoryService(session=session).set_active(category_id=category_id, is_active=False)
        await state.clear()
        text = await _render_admin_categories(session)
        await message.answer("Категория отключена.", reply_markup=_admin_categories_menu_keyboard())
        await message.answer(text, reply_markup=_admin_categories_menu_keyboard())
        return

    if edit_action == "enable":
        await CategoryService(session=session).set_active(category_id=category_id, is_active=True)
        await state.clear()
        text = await _render_admin_categories(session)
        await message.answer("Категория включена.", reply_markup=_admin_categories_menu_keyboard())
        await message.answer(text, reply_markup=_admin_categories_menu_keyboard())
        return

    await state.update_data(edit_category_id=category_id)
    await state.set_state(AdminCategoryState.waiting_for_edit_value)

    if edit_action == "total":
        await message.answer("Введите `total_upload_limit` (число) или '-' для без лимита.", parse_mode="Markdown")
    elif edit_action == "rate":
        await message.answer("Введите `payout_rate` (число, например 100.00).", parse_mode="Markdown")
    elif edit_action == "desc":
        await message.answer("Введите новое описание. '-' — без описания.", parse_mode="Markdown")
    else:
        await state.clear()
        await message.answer("Неизвестное действие. Начни заново.", reply_markup=_admin_categories_menu_keyboard())


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
    await message.answer(text, reply_markup=_admin_categories_menu_keyboard())


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
    recipients = await UserService(session=session).get_all_active_users()
    delivered = 0
    failed = 0
    for user in recipients:
        try:
            await bot.send_message(chat_id=user.telegram_id, text=message.text.strip())
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
    """Задаёт дневной лимит выгрузок: telegram_id и число."""

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
        await message.answer(
            "Нужна строка из трёх чисел: telegram_id, id категории и лимит. Пример: 123456789 12 10"
        )
        return
    tg_id = int(m.group(1))
    category_id = int(m.group(2))
    limit = int(m.group(3))
    if limit < 0:
        await message.answer("Лимит не может быть отрицательным.")
        return
    user = await UserService(session=session).get_by_telegram_id(tg_id)
    if user is None:
        await message.answer("Пользователь с таким telegram_id не найден.")
        return
    if user.role not in (UserRole.SELLER, UserRole.CHIEF_ADMIN):
        await message.answer("Квоты задаются только для продавцов и главного админа.")
        return
    category = await CategoryService(session=session).get_by_id(category_id)
    if category is None or not category.is_active:
        await message.answer("Категория с таким id не найдена или неактивна.")
        return
    today = datetime.now(timezone.utc).date()
    await SellerQuotaService(session=session).upsert_quota(user.id, category_id, today, limit)
    await state.clear()
    await message.answer(
        f"На {today} (UTC) для @{user.username or tg_id} в «{category.title}» (id {category_id}): лимит {limit} выгрузок.",
        reply_markup=admin_main_menu_keyboard(),
    )


@router.message(Command("daily_report"))
@router.message(F.text.func(_reply_matches_menu_label("Выплаты")))
async def on_daily_report(message: Message, session: AsyncSession) -> None:
    """Показывает итоговую ведомость к выплате."""

    if message.from_user is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    rows = await BillingService(session=session).get_daily_report_rows()
    if not rows:
        await message.answer("Нет пользователей с балансом к выплате.")
        return

    first = True
    for row in rows:
        body = (
            f"{row['username']} | {row['accepted_count']} accepted | "
            f"To pay: {row['to_pay']} USDT"
        )
        if first:
            body = f"{HINT_PAYOUTS}\n\n{body}"
            first = False
        await message.answer(
            text=body,
            reply_markup=payout_mark_paid_keyboard(user_id=int(row["user_id"])),
        )


@router.message(F.text.func(_reply_matches_menu_label("Архив (7days)")))
async def on_archive_help(message: Message, session: AsyncSession) -> None:
    """Показывает, как искать номер в архиве за 7 дней."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
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
                f"Номер: {submission.description_text}\n"
                f"Статус: {submission.status.value}"
            ),
            reply_markup=search_report_keyboard(submission_id=submission.id, seller_user_id=submission.user_id),
        )
    await message.answer(
        "Навигация архива:",
        reply_markup=pagination_keyboard("admin:archive_page", page=0, total=total, page_size=PAGE_SIZE, query=query),
    )


@router.callback_query(F.data.startswith("admin:archive_page:"))
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
                    f"Номер: {submission.description_text}\n"
                    f"Статус: {submission.status.value}"
                ),
                reply_markup=search_report_keyboard(submission_id=submission.id, seller_user_id=submission.user_id),
            )
        await callback.message.answer(
            "Навигация архива:",
            reply_markup=pagination_keyboard("admin:archive_page", page=page, total=total, page_size=PAGE_SIZE, query=query),
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
                f"Номер: {submission.description_text}\n"
                f"Статус: {submission.status.value}"
            ),
            reply_markup=search_report_keyboard(submission_id=submission.id, seller_user_id=submission.user_id),
        )
    await message.answer(
        "Навигация поиска:",
        reply_markup=pagination_keyboard("admin:search_page", page=0, total=total, page_size=PAGE_SIZE, query=raw_query),
    )


@router.callback_query(F.data.startswith("admin:search_page:"))
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
                    f"Номер: {submission.description_text}\n"
                    f"Статус: {submission.status.value}"
                ),
                reply_markup=search_report_keyboard(submission_id=submission.id, seller_user_id=submission.user_id),
            )
        await callback.message.answer(
            "Навигация поиска:",
            reply_markup=pagination_keyboard("admin:search_page", page=page, total=total, page_size=PAGE_SIZE, query=query),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:restrict:"))
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


@router.callback_query(F.data.startswith("admin:unrestrict:"))
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
    await message.answer_document(document=("daily_report.csv", sio.getvalue().encode("utf-8")), caption="Экспорт CSV готов.")


@router.callback_query(lambda c: c.data is not None and c.data.startswith("pay:mark:"))
async def on_mark_paid(callback: CallbackQuery, session: AsyncSession) -> None:
    """Фиксирует выплату пользователю и обнуляет pending_balance."""

    if callback.from_user is None or callback.data is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await callback.answer("Админ не найден в БД", show_alert=True)
        return

    user_id = int(callback.data.split(":")[2])
    payout = await BillingService(session=session).mark_user_paid(
        user_id=user_id,
        paid_by_admin_id=admin_user.id,
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
        details=f"amount={payout.amount}",
    )
    if callback.message is not None:
        await callback.message.edit_text(f"{callback.message.text}\n\nСтатус: выплачено ({payout.amount} USDT)")


@router.callback_query(F.data.startswith("admin:report_submission:"))
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
        select(ReviewAction)
        .where(ReviewAction.submission_id == submission.id)
        .order_by(ReviewAction.created_at.asc())
    )
    actions = list((await session.execute(actions_stmt)).scalars().all())
    history_lines = [
        f"- {action.created_at}: {action.from_status.value if action.from_status else 'none'} -> {action.to_status.value}"
        for action in actions
    ]
    history_text = "\n".join(history_lines) if history_lines else "- без изменений статуса"

    report_text = (
        f"Отчёт по товару #{submission.id}\n"
        f"Продавец: {seller_nickname}\n"
        f"Номер: {submission.description_text}\n"
        f"Текущий статус: {submission.status.value}\n"
        f"Создано: {submission.created_at}\n"
        f"Взято в работу: {submission.assigned_at}\n"
        f"Проверено: {submission.reviewed_at}\n"
        f"Начислено: {submission.accepted_amount}\n\n"
        "История статусов:\n"
        f"{history_text}"
    )
    await callback.answer()
    await callback.message.answer(report_text)  # type: ignore[union-attr]
