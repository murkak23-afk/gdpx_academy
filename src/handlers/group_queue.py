"""Команды очереди для групп: /sim в супергруппе/группе.

Любой пользователь, являющийся ботовым администратором (роль admin),
может выполнить команду прямо в группе/супергруппе, где боту выданы права.
Бот показывает список pending-карточек по категориям и позволяет переслать
нужное количество прямо в текущий чат.
"""

from __future__ import annotations

import logging
import re
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.database.models.category import Category
from src.database.models.enums import RejectionReason, SubmissionStatus
from src.database.models.submission import Submission
from src.database.models.user import User
from src.services import (
    AdminAuditService,
    AdminChatForwardStatsService,
    AdminService,
    SubmissionService,
    UserService,
)
from src.utils.phone_norm import normalize_phone_key
from src.utils.submission_format import format_submission_chat_forward_title
from src.utils.submission_media import bot_send_submission

router = Router(name="group-queue-router")
logger = logging.getLogger(__name__)

_GROUP_TYPES = {"group", "supergroup"}
_active_menu_by_thread: dict[tuple[int, int | None], int] = {}
_pending_qty_input: dict[tuple[int, int, int | None], int] = {}
_pending_hold_choice: dict[tuple[int, int, int | None], tuple[int, int]] = {}

# ---------- callback-префиксы (локальные, не пересекаются с другими роутерами) ----------
_CB_QUEUE = "sim_q"           # обновить список категорий
_CB_CAT = "sim_q_cat"         # выбрать категорию → показать qty
_CB_FWD = "sim_q_fwd"         # переслать N штук: sim_q_fwd:{cat_id}:{qty}
_CB_QTY_INPUT = "sim_q_input"  # запрос ручного ввода количества
_CB_HOLD = "sim_q_hold"       # выбор hold после количества

# ---------- Авто-фиксация: конфигурация чатов и топиков ----------
#
# Формат: chat_id → { topic_id: "действие" }
#
# Доступные действия:
#   "blocked"    — БЛОК (нарушение правил)
#   "not_a_scan" — НЕ СКАН (качество)
#   "rejected"   — БРАК (качество)
#
# Чтобы подключить новый чат — добавь блок.
# Чтобы добавить топик в чат — добавь строку topic_id: "действие".

AUTO_FIX_CHATS: dict[int, dict[int, str]] = {

    # ── Чат 1: GDPX основной ──
    -1003724834316: {
        76:  "blocked",       # топик «Блоки»
        188: "not_a_scan",    # топик «Не сканы»
    },

    # ── Чат 2: (пример — раскомментируй и подставь свои id) ──
    -1003129572986: {
         13947: "blocked",
         13949: "not_a_scan",
    },

    # ── Чат 3: ──
    # -100YYYYYYYYYY: {
    #     10: "blocked",
    # },

}

# ---------- внутренняя механика (не трогать) ----------

from dataclasses import dataclass as _dataclass


@_dataclass(frozen=True, slots=True)
class AutoFixRule:
    status: SubmissionStatus
    reason: RejectionReason
    label: str
    audit_action: str


_ACTION_PRESETS: dict[str, AutoFixRule] = {
    "blocked": AutoFixRule(
        status=SubmissionStatus.BLOCKED,
        reason=RejectionReason.RULES_VIOLATION,
        label="BLOCKED",
        audit_action="auto_mark_blocked",
    ),
    "not_a_scan": AutoFixRule(
        status=SubmissionStatus.NOT_A_SCAN,
        reason=RejectionReason.QUALITY,
        label="НЕ SCAN",
        audit_action="auto_mark_not_a_scan",
    ),
    "rejected": AutoFixRule(
        status=SubmissionStatus.REJECTED,
        reason=RejectionReason.QUALITY,
        label="БРАК",
        audit_action="auto_mark_rejected",
    ),
}


def _build_rules() -> dict[tuple[int, int], AutoFixRule]:
    rules: dict[tuple[int, int], AutoFixRule] = {}
    for chat_id, topics in AUTO_FIX_CHATS.items():
        for topic_id, action in topics.items():
            preset = _ACTION_PRESETS.get(action)
            if preset is None:
                raise ValueError(
                    f"AUTO_FIX_CHATS: неизвестное действие '{action}' "
                    f"для chat_id={chat_id}, topic_id={topic_id}. "
                    f"Допустимые: {list(_ACTION_PRESETS.keys())}"
                )
            rules[(chat_id, topic_id)] = preset
    return rules


_AUTO_FIX_RULES = _build_rules()


def _get_auto_fix_rule(chat_id: int, topic_id: int | None) -> AutoFixRule | None:
    if topic_id is None:
        return None
    return _AUTO_FIX_RULES.get((chat_id, topic_id))


_STATUS_ALIASES: dict[str, tuple[SubmissionStatus, RejectionReason]] = {
    "блок": (SubmissionStatus.BLOCKED, RejectionReason.RULES_VIOLATION),
    "blocked": (SubmissionStatus.BLOCKED, RejectionReason.RULES_VIOLATION),
    "block": (SubmissionStatus.BLOCKED, RejectionReason.RULES_VIOLATION),
    "не скан": (SubmissionStatus.NOT_A_SCAN, RejectionReason.QUALITY),
    "нескан": (SubmissionStatus.NOT_A_SCAN, RejectionReason.QUALITY),
    "not_a_scan": (SubmissionStatus.NOT_A_SCAN, RejectionReason.QUALITY),
    "not scan": (SubmissionStatus.NOT_A_SCAN, RejectionReason.QUALITY),
    "брак": (SubmissionStatus.REJECTED, RejectionReason.QUALITY),
    "reject": (SubmissionStatus.REJECTED, RejectionReason.OTHER),
    "rejected": (SubmissionStatus.REJECTED, RejectionReason.OTHER),
}

_STATUS_LABELS: dict[SubmissionStatus, str] = {
    SubmissionStatus.BLOCKED: "блок",
    SubmissionStatus.NOT_A_SCAN: "не скан",
    SubmissionStatus.REJECTED: "брак",
}


async def _in_review_phone_snapshots(
    session: AsyncSession,
    phone_norm: str,
    is_partial: bool = False,
) -> list[dict[str, int | str | None]]:
    if is_partial:
        cond = Submission.phone_normalized.like(f"%{phone_norm}")
    else:
        plus_variant = f"+{phone_norm}"
        cond = (
            (Submission.phone_normalized == phone_norm)
            | (Submission.description_text == phone_norm)
            | (Submission.description_text == plus_variant)
        )
    stmt = (
        select(
            Submission.id,
            Submission.user_id,
            Submission.admin_id,
            Submission.description_text,
        )
        .where(
            Submission.status == SubmissionStatus.IN_REVIEW,
            cond,
        )
        .order_by(Submission.id.asc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            "id": int(row[0]),
            "user_id": int(row[1]),
            "admin_id": int(row[2]) if row[2] is not None else None,
            "description_text": str(row[3] or ""),
        }
        for row in rows
    ]


async def _notify_autofix_sides(
    *,
    bot: Bot,
    session: AsyncSession,
    snapshots: list[dict[str, int | str | None]],
    phone_norm: str,
    count: int,
    status_label: str,
) -> None:
    """Уведомляет продавцов и контролёров об авто-фиксации статуса."""
    notified_chat_ids: set[int] = set()
    seller_ids = {int(s["user_id"]) for s in snapshots if s.get("user_id") is not None}
    controller_ids = {
        int(s["admin_id"])
        for s in snapshots
        if s.get("admin_id") is not None
    }

    for seller_id in seller_ids:
        seller = await session.get(User, seller_id)
        if seller is None:
            continue
        if int(seller.telegram_id) in notified_chat_ids:
            continue
        try:
            await bot.send_message(
                chat_id=seller.telegram_id,
                text=(
                    f"⚠️ Номеру +{phone_norm} присвоен статус: <b>{status_label}</b>.\n"
                    f"Количество: <b>{count}</b>."
                ),
                parse_mode="HTML",
            )
            notified_chat_ids.add(int(seller.telegram_id))
        except TelegramAPIError:
            pass

    for controller_id in controller_ids:
        controller = await session.get(User, controller_id)
        if controller is None:
            continue
        if int(controller.telegram_id) in notified_chat_ids:
            continue
        try:
            await bot.send_message(
                chat_id=controller.telegram_id,
                text=(
                    f"⚠️ Номеру +{phone_norm} присвоен статус: <b>{status_label}</b>.\n"
                    f"Количество сим: <b>{count}</b>."
                ),
                parse_mode="HTML",
            )
            notified_chat_ids.add(int(controller.telegram_id))
        except TelegramAPIError:
            pass


def _parse_topic_id_from_queue_text(text: str | None) -> int | None:
    """Поддерживает /sim 123 и /sim topic=123."""

    if not text:
        return None
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return None
    arg = parts[1].strip()
    if arg.isdigit():
        return int(arg)
    m = re.search(r"topic\s*=\s*(\d+)", arg, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _extract_target_thread_id(message: Message) -> int | None:
    """Возвращает topic id из команды или текущей темы, если команда вызвана в теме."""

    parsed = _parse_topic_id_from_queue_text(message.text)
    if parsed is not None:
        return parsed
    if message.message_thread_id is not None:
        return message.message_thread_id
    if message.reply_to_message is not None and message.reply_to_message.message_thread_id is not None:
        return message.reply_to_message.message_thread_id
    return None


def _extract_all_phones_or_suffixes(text: str) -> list[tuple[str, bool]]:
    """Извлекает ВСЕ номера/суффиксы из текста (по одному на строку).

    Returns list of (value, is_partial):
      - is_partial=False: полный нормализованный номер 7XXXXXXXXXX (11 цифр)
      - is_partial=True:  суффикс 4-9 цифр (поиск по окончанию phone_normalized)
    Распознаёт: +7/8/7 с кодом, номер без 7 в начале (10 цифр), последние 4-9 цифр.
    """
    results: list[tuple[str, bool]] = []
    seen: set[str] = set()
    # Разбиваем по строкам, чтобы \n не склеивал номера в один жадный матч.
    for line in text.splitlines():
        # Сначала пробуем извлечь полный номер (11 цифр или 10 цифр → нормализуем до 11)
        found_full = False
        for chunk in re.findall(r"[+\d][\d \t\-()]{6,24}", line):
            normalized = normalize_phone_key(chunk)
            if normalized is not None and len(normalized) == 11 and normalized.startswith("7"):
                if normalized not in seen:
                    results.append((normalized, False))
                    seen.add(normalized)
                found_full = True
                break
        if found_full:
            continue
        # Затем ищем суффикс: 4-9 цифр подряд (без пробелов внутри)
        for chunk in re.findall(r"(?<!\d)(\d{4,9})(?!\d)", line):
            if chunk not in seen:
                results.append((chunk, True))
                seen.add(chunk)
            break
    return results


def _extract_phone_or_suffix(text: str) -> tuple[str, bool] | None:
    """Извлекает первый номер из текста (обратная совместимость)."""
    results = _extract_all_phones_or_suffixes(text)
    return results[0] if results else None


# Backward-compatible alias (используется в _parse_group_status_change_request)
def _extract_first_phone_normalized(text: str) -> str | None:
    result = _extract_phone_or_suffix(text)
    if result is None:
        return None
    value, is_partial = result
    return None if is_partial else value


def _status_alias_match(text_lower: str) -> tuple[SubmissionStatus, RejectionReason] | None:
    for alias, result in sorted(_STATUS_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = rf"(^|\W){re.escape(alias).replace('\\ ', r'\s+')}($|\W)"
        if re.search(pattern, text_lower, flags=re.IGNORECASE):
            return result
    return None


def _parse_group_status_change_request(
    text: str,
) -> tuple[SubmissionStatus, RejectionReason, str, str] | None:
    """Парсит запрос смены статуса: статус + номер + комментарий."""

    raw = text.strip()
    lower = raw.lower()
    if not (
        lower.startswith("/simstatus")
        or lower.startswith("simstatus")
        or "#sim" in lower
    ):
        return None

    status_meta = _status_alias_match(lower)
    if status_meta is None:
        return None
    phone_norm = _extract_first_phone_normalized(raw)
    if phone_norm is None:
        return None

    status, reason = status_meta
    comment = f"Группа: авто-статус {_STATUS_LABELS.get(status, status.value)} по номеру {phone_norm}"
    return status, reason, phone_norm, comment


async def _send_to_thread(
    *,
    source_message: Message,
    text: str,
    thread_id: int | None,
    parse_mode: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
    """Безопасная отправка в тему без дублирования message_thread_id."""

    kwargs: dict = {
        "chat_id": source_message.chat.id,
        "text": text,
    }
    if thread_id is not None:
        kwargs["message_thread_id"] = thread_id
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup
    return await source_message.bot.send_message(**kwargs)


def _menu_key(chat_id: int, thread_id: int | None) -> tuple[int, int | None]:
    return (chat_id, thread_id)


def _qty_input_key(user_id: int, chat_id: int, thread_id: int | None) -> tuple[int, int, int | None]:
    return (user_id, chat_id, thread_id)


async def _close_active_menu(bot: Bot, chat_id: int, thread_id: int | None) -> None:
    prev_message_id = _active_menu_by_thread.get(_menu_key(chat_id, thread_id))
    if not prev_message_id:
        return
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=prev_message_id,
            reply_markup=None,
        )
    except TelegramAPIError:
        pass


def _remember_active_menu(message: Message) -> None:
    _active_menu_by_thread[_menu_key(message.chat.id, message.message_thread_id)] = message.message_id


async def _render_queue_menu(
    *,
    target_message: Message,
    session: AsyncSession,
    thread_id: int | None,
) -> Message | None:
    rows = await _pending_by_category(session)
    total = sum(cnt for _, cnt in rows)
    if not rows:
        refresh_kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔄 Обновить", callback_data=_CB_QUEUE)]]
        )
        await edit_message_text_or_caption_safe(
            target_message,
            text="📭 Очередь пустая.",
            reply_markup=refresh_kb,
        )
        return target_message

    sent = await _send_to_thread(
        source_message=target_message,
        text=f"📋 <b>Очередь</b> — всего: <b>{total}</b> шт.\n\nВыбери категорию:",
        thread_id=thread_id,
        parse_mode="HTML",
        reply_markup=_queue_keyboard(rows),
    )
    _remember_active_menu(sent)
    return sent


# ---------- вспомогательные функции ----------

async def _pending_by_category(session: AsyncSession) -> list[tuple[Category, int]]:
    """Возвращает [(категория, кол-во pending)], сортировка по убыванию кол-ва."""
    stmt = (
        select(Category, func.count(Submission.id).label("cnt"))
        .join(Submission, Submission.category_id == Category.id)
        .where(Submission.status == SubmissionStatus.PENDING, Category.is_active.is_(True))
        .group_by(Category.id)
        .order_by(func.count(Submission.id).desc())
    )
    rows = (await session.execute(stmt)).all()
    return [(row[0], int(row[1])) for row in rows]


def _queue_keyboard(rows: list[tuple[Category, int]]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for cat, cnt in rows:
        label = f"{cat.compose_title()} — {cnt} шт."
        buttons.append([
            InlineKeyboardButton(text=label, callback_data=f"{_CB_CAT}:{cat.id}")
        ])
    buttons.append([InlineKeyboardButton(text="🔄 Обновить", callback_data=_CB_QUEUE)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _qty_keyboard(category_id: int, available: int) -> InlineKeyboardMarkup:
    presets = [1, 5, 10, 20, 50, 100, 200, 500, 999]
    row_presets = [
        InlineKeyboardButton(text=str(q), callback_data=f"{_CB_FWD}:{category_id}:{q}")
        for q in presets
        if q <= min(available, 999)
    ]
    input_btn = InlineKeyboardButton(
        text="✍️ Количество:", callback_data=f"{_CB_QTY_INPUT}:{category_id}"
    )
    back_btn = InlineKeyboardButton(text="◀️ Назад", callback_data=_CB_QUEUE)
    kb: list[list[InlineKeyboardButton]] = []
    if row_presets:
        kb.append(row_presets)
    kb.append([input_btn])
    kb.append([back_btn])
    return InlineKeyboardMarkup(inline_keyboard=kb)




def _hold_label(hold_value: str | None) -> str:
    if not hold_value:
        return "не указан"
    if hold_value == "no_hold":
        return "Без холда"
    return hold_value


async def _notify_seller(bot: Bot, user: User, description_text: str | None, hold_value: str | None) -> None:
    num = (description_text or "").strip() or "—"
    try:
        await bot.send_message(
            chat_id=user.telegram_id,
            text=(
                f"⚖️ Ваша симка <code>{escape(num)}</code> передана на скан.\n"
                f"⏱ Холд: <b>{escape(_hold_label(hold_value))}</b>\n"
                "Ожидайте решения."
            ),
            parse_mode="HTML",
        )
    except TelegramAPIError:
        pass


# ---------- команда /simsetup — регистрация команд для чата ----------

_SIM_GROUP_COMMANDS = [
    BotCommand(command="sim", description="📋 Очередь симок — отправить карточки"),
    BotCommand(command="simsetup", description="⚙️ Зарегистрировать /sim в меню этого чата"),
]


@router.message(Command("simsetup"), F.chat.type.in_(_GROUP_TYPES))
async def cmd_simsetup(message: Message, session: AsyncSession, bot: Bot) -> None:
    """Регистрирует /sim, /simpin, /simsetup в меню команд именно этого чата.

    После выполнения участники видят подсказки при вводе / в данном чате.
    """
    if message.from_user is None:
        return
    if not await AdminService(session=session).can_use_sim_groups(message.from_user.id):
        return

    try:
        await bot.set_my_commands(
            commands=_SIM_GROUP_COMMANDS,
            scope=BotCommandScopeChat(chat_id=message.chat.id),
        )
    except TelegramAPIError as exc:
        await message.answer(f"⚠️ Не удалось зарегистрировать команды: {exc}")
        return

    try:
        await message.delete()
    except TelegramAPIError:
        pass

    await message.answer(
        "✅ Команды зарегистрированы для этого чата.\n"
        "Теперь при вводе <code>/</code> участники видят <b>/sim</b>, <b>/simsetup</b>.",
        parse_mode="HTML",
    )


# ---------- команда /sim ----------

@router.message(Command("sim"), F.chat.type.in_(_GROUP_TYPES))
async def cmd_group_queue(message: Message, session: AsyncSession) -> None:
    """Показывает список категорий с кол-вом pending; только для ботовых админов."""
    if message.from_user is None:
        return
    if not await AdminService(session=session).can_use_sim_groups(message.from_user.id):
        return  # молчим — не спамим в чат отказом

    thread_id = _extract_target_thread_id(message)
    is_forum_chat = bool(getattr(message.chat, "is_forum", False))

    # В forum-чате не даём молча уходить в #general, если тема не определена.
    if is_forum_chat and thread_id is None:
        await message.answer(
            "Не удалось определить тему. Запусти /sim внутри нужной темы "
            "или укажи её явно: /sim topic_id (или /sim topic=topic_id).",
        )
        return

    # Форсируем работу по topic id только в forum-темах (или если команда вызвана из темы).
    if _parse_topic_id_from_queue_text(message.text) is not None and thread_id is None:
        await message.answer(
            "Некорректный topic id. Используй /sim topic_id или запусти /sim внутри нужной темы.",
        )
        return

    await _close_active_menu(message.bot, message.chat.id, thread_id)
    await _render_queue_menu(target_message=message, session=session, thread_id=thread_id)


# ---------- обновить список ----------

@router.callback_query(F.data == _CB_QUEUE, F.message.chat.type.in_(_GROUP_TYPES))
async def cb_queue_refresh(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not await AdminService(session=session).can_use_sim_groups(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    rows = await _pending_by_category(session)
    total = sum(cnt for _, cnt in rows)
    await callback.answer()

    if not rows:
        await edit_message_text_or_caption_safe(callback.message, text="📭 Очередь пустая.")
        return

    await edit_message_text_or_caption_safe(
        callback.message,
        text=f"📋 <b>Очередь</b> — всего: <b>{total}</b> шт.\n\nВыбери категорию:",
        parse_mode="HTML",
        reply_markup=_queue_keyboard(rows),
    )
    _remember_active_menu(callback.message)


# ---------- выбрать категорию → показать qty ----------

@router.callback_query(F.data.startswith(f"{_CB_CAT}:"), F.message.chat.type.in_(_GROUP_TYPES))
async def cb_queue_cat(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None or callback.message is None:
        return
    if not await AdminService(session=session).can_use_sim_groups(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    category_id = int(callback.data.split(":")[1])
    cat = await session.get(Category, category_id)
    if cat is None:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    count_stmt = (
        select(func.count(Submission.id))
        .where(
            Submission.status == SubmissionStatus.PENDING,
            Submission.category_id == category_id,
        )
    )
    count = int((await session.execute(count_stmt)).scalar_one())
    await callback.answer()

    if count == 0:
        await edit_message_text_or_caption_safe(
            callback.message,
            text=f"📭 В категории <b>{escape(cat.compose_title())}</b> нет карточек в очереди.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data=_CB_QUEUE)]]
            ),
        )
        return

    await edit_message_text_or_caption_safe(
        callback.message,
        text=f"📦 <b>{escape(cat.compose_title())}</b>\n"
        f"Доступно: <b>{count}</b> шт.\n\n"
        "Сколько карточек отправить в этот чат? (1..999)",
        parse_mode="HTML",
        reply_markup=_qty_keyboard(category_id, count),
    )
    _remember_active_menu(callback.message)


async def _forward_for_category(
    *,
    actor_tg_id: int,
    target_message: Message,
    session: AsyncSession,
    bot: Bot,
    category_id: int,
    qty: int,
    selected_hold: str,
    callback: CallbackQuery | None = None,
) -> None:
    cat = await session.get(Category, category_id)
    if cat is None:
        if callback is not None:
            await callback.answer("Категория не найдена", show_alert=True)
        else:
            await target_message.answer("Категория не найдена")
        return

    safe_qty = max(1, min(int(qty), 999))
    stmt = (
        select(Submission)
        .options(joinedload(Submission.category), joinedload(Submission.seller))
        .where(
            Submission.status == SubmissionStatus.PENDING,
            Submission.category_id == category_id,
        )
        .order_by(Submission.created_at.asc())
        .limit(safe_qty)
    )

    submissions = list((await session.execute(stmt)).scalars().all())
    if not submissions:
        if callback is not None:
            await callback.answer("Нет карточек для отправки", show_alert=True)
        else:
            await target_message.answer("Нет карточек для отправки")
        return

    admin_user = await UserService(session=session).get_by_telegram_id(actor_tg_id)
    if admin_user is None:
        if callback is not None:
            await callback.answer("Пользователь не найден в БД", show_alert=True)
        else:
            await target_message.answer("Пользователь не найден в БД")
        return

    target_chat_id = target_message.chat.id
    target_thread_id = target_message.message_thread_id
    if callback is not None:
        await callback.answer(f"Отправляю {len(submissions)} шт…")
        if callback.message is not None:
            await callback.message.edit_reply_markup(reply_markup=None)
    else:
        await _send_to_thread(
            source_message=target_message,
            text=f"Отправляю {len(submissions)} шт…",
            thread_id=target_thread_id,
        )

    hold_default = (cat.hold_condition or "").strip() or None
    if selected_hold == "cat":
        hold_to_assign = hold_default
    else:
        hold_to_assign = selected_hold

    sent_count = 0
    failed_ids: list[int] = []
    for item in submissions:
        try:
            await bot_send_submission(
                bot,
                target_chat_id,
                item,
                caption=format_submission_chat_forward_title(item, hold_override=hold_to_assign),
                **({"message_thread_id": target_thread_id} if target_thread_id is not None else {}),
            )
            sent_count += 1
        except TelegramAPIError as exc:
            logger.warning(
                "group_queue forward error submission_id=%s chat_id=%s: %s",
                item.id, target_chat_id, exc,
            )
            failed_ids.append(item.id)

    successfully_sent = [s for s in submissions if s.id not in set(failed_ids)]

    if successfully_sent:
        for s in successfully_sent:
            s.hold_assigned = hold_to_assign
            session.add(s)

    marked = await SubmissionService(session=session).mark_submissions_in_review(
        submissions=successfully_sent,
        admin_id=admin_user.id,
    )

    for s in marked:
        seller = await session.get(User, s.user_id)
        if seller is not None:
            await _notify_seller(bot, seller, s.description_text, s.hold_assigned)

    if sent_count > 0:
        await AdminChatForwardStatsService(session=session).add_forwards_for_telegram_chat(
            target_chat_id, sent_count
        )
    await AdminAuditService(session=session).log(
        admin_id=admin_user.id,
        action="group_queue_forward",
        target_type="category",
        target_id=category_id,
        details=(
            f"chat_id={target_chat_id}, thread_id={target_thread_id}, "
            f"cat={cat.compose_title()}, hold={hold_to_assign}, "
            f"requested={safe_qty}, sent={sent_count}, failed={failed_ids}"
        ),
    )

    lines: list[str] = [f"✅ Отправлено: <b>{sent_count}</b> шт."]
    if failed_ids:
        lines.append(f"❌ Ошибок: <b>{len(failed_ids)}</b>")

    rows = await _pending_by_category(session)
    total_left = sum(cnt for _, cnt in rows)
    if rows:
        lines.append(f"\n📋 Осталось в очереди: <b>{total_left}</b> шт.")

    sent = await _send_to_thread(
        source_message=target_message,
        text="\n".join(lines),
        thread_id=target_thread_id,
        parse_mode="HTML",
        reply_markup=_queue_keyboard(rows) if rows else None,
    )
    _remember_active_menu(sent)


# ---------- переслать N штук ----------

@router.callback_query(F.data.startswith(f"{_CB_FWD}:"), F.message.chat.type.in_(_GROUP_TYPES))
async def cb_group_forward(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    if callback.from_user is None or callback.data is None or callback.message is None:
        return
    if not await AdminService(session=session).can_use_sim_groups(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    parts = callback.data.split(":")
    category_id = int(parts[1])
    qty = int(parts[2])
    cat = await session.get(Category, category_id)
    if cat is None:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    # --- Спецлогика: если чат в списке instant-hold, выдаём симки сразу без выбора hold ---
    await _forward_for_category(
        actor_tg_id=callback.from_user.id,
        target_message=callback.message,
        session=session,
        bot=bot,
        category_id=category_id,
        qty=qty,
        selected_hold="no_hold",
        callback=callback,
    )
    return


import asyncio


@router.callback_query(F.data.startswith(f"{_CB_QTY_INPUT}:"), F.message.chat.type.in_(_GROUP_TYPES))
async def cb_queue_qty_input(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    if callback.from_user is None or callback.data is None or callback.message is None:
        return
    if not await AdminService(session=session).can_use_sim_groups(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    category_id = int(callback.data.split(":")[1])
    key = _qty_input_key(callback.from_user.id, callback.message.chat.id, callback.message.message_thread_id)
    _pending_qty_input[key] = category_id
    await callback.answer()
    await _send_to_thread(
        source_message=callback.message,
        text="Введи количество для отправки (от 1 до 999).",
        thread_id=callback.message.message_thread_id,
    )

    # Таймаут 10 секунд на ввод
    async def timeout_clear():
        await asyncio.sleep(10)
        # Если пользователь не ввёл число за 10 секунд, сбрасываем ожидание (без уведомления)
        _pending_qty_input.pop(key, None)

    asyncio.create_task(timeout_clear())


@router.message(F.chat.type.in_(_GROUP_TYPES))
async def on_queue_qty_input_message(message: Message, session: AsyncSession, bot: Bot) -> None:
    if message.from_user is None:
        return

    raw_text = (message.text or message.caption or "").strip()
    key = _qty_input_key(message.from_user.id, message.chat.id, message.message_thread_id)
    category_id = _pending_qty_input.get(key)

    # Авто-фиксация: ищем правило по (chat_id, topic_id)
    rule = _get_auto_fix_rule(message.chat.id, message.message_thread_id)
    if rule is not None:
        all_phones = _extract_all_phones_or_suffixes(raw_text)
        if not all_phones:
            return

        actor_user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
        reply_parts: list[str] = []

        for phone_norm, is_partial in all_phones:
            display_phone = f"…{phone_norm}" if is_partial else f"+{phone_norm}"

            snapshots = await _in_review_phone_snapshots(session, phone_norm, is_partial=is_partial)
            if not snapshots:
                reply_parts.append(f"⚠️ По номеру {display_phone} в разделе 'В работе' ничего не найдено.")
                # Новое уведомление в топик, если номера нет в базе
                await _send_to_thread(
                    source_message=message,
                    text="Номера нет в базе... Теперь напрягаем пальцы 🔎",
                    thread_id=message.message_thread_id,
                )
                continue

            comment_prefix = f"Авто-{rule.label} из чата {message.chat.id}, топик {message.message_thread_id}"
            if is_partial:
                changed = await SubmissionService(session=session).final_reject_in_review_by_phone_suffix(
                    suffix=phone_norm,
                    admin_id=None,
                    to_status=rule.status,
                    reason=rule.reason,
                    comment=f"{comment_prefix}, суффикс …{phone_norm}",
                )
            else:
                changed = await SubmissionService(session=session).final_reject_in_review_by_phone(
                    phone=phone_norm,
                    admin_id=None,
                    to_status=rule.status,
                    reason=rule.reason,
                    comment=f"{comment_prefix}, номер {phone_norm}",
                )

            if not changed:
                reply_parts.append(f"⚠️ Номер {display_phone} не обнаружен, возможно указаны не те цифры!")
                continue

            if actor_user is not None:
                await AdminAuditService(session=session).log(
                    admin_id=actor_user.id,
                    action=rule.audit_action,
                    target_type="phone",
                    details=(
                        f"chat_id={message.chat.id}, thread_id={message.message_thread_id}, "
                        f"phone={phone_norm}, partial={is_partial}, count={len(changed)}, ids={[item.id for item in changed][:20]}"
                    ),
                )

            await _notify_autofix_sides(
                bot=bot,
                session=session,
                snapshots=snapshots,
                phone_norm=phone_norm,
                count=len(changed),
                status_label=rule.label,
            )

            logger.info(
                "auto-fix applied rule=%s chat_id=%s thread_id=%s phone=%s partial=%s count=%s",
                rule.label,
                message.chat.id,
                message.message_thread_id,
                phone_norm,
                is_partial,
                len(changed),
            )

            reply_parts.append(f"⚠️ Номеру {display_phone} присвоен статус '{rule.label}' ({len(changed)} шт.).")

        await _send_to_thread(
            source_message=message,
            text="\n".join(reply_parts),
            thread_id=message.message_thread_id,
        )

        if message.text is None:
            return
        if not await AdminService(session=session).can_use_sim_groups(message.from_user.id):
            return

        if category_id is None:
            parsed = _parse_group_status_change_request(message.text)
            if parsed is None:
                return

            to_status, reason, phone_norm, comment = parsed
            admin_user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
            if admin_user is None:
                return

            changed = await SubmissionService(session=session).final_reject_in_review_by_phone(
                phone=phone_norm,
                admin_id=admin_user.id,
                to_status=to_status,
                reason=reason,
                comment=comment,
            )

            await AdminAuditService(session=session).log(
                admin_id=admin_user.id,
                action="group_status_by_phone",
                target_type="phone",
                details=(
                    f"chat_id={message.chat.id}, thread_id={message.message_thread_id}, "
                    f"phone={phone_norm}, to_status={to_status.value}, count={len(changed)}, "
                    f"ids={[item.id for item in changed][:20]}"
                ),
            )

            if not changed:
                await _send_to_thread(
                    source_message=message,
                    text=(
                        f"По номеру +{phone_norm} нет карточек со статусом IN_REVIEW. "
                        "Ничего не изменено."
                    ),
                    thread_id=message.message_thread_id,
                )
                return

            await _send_to_thread(
                source_message=message,
                text=(
                    f"Обновлено: {len(changed)} шт.\n"
                    f"Номер: +{phone_norm}\n"
                    f"Новый статус: {_STATUS_LABELS.get(to_status, to_status.value)}"
                ),
                thread_id=message.message_thread_id,
            )
            return

    if not message.text:
        return
    text = message.text.strip()
    if category_id is not None:
        if not text.isdigit():
            await _send_to_thread(
                source_message=message,
                text="Нужно число от 1 до 999.",
                thread_id=message.message_thread_id,
            )
            return
        qty = int(text)
        if qty < 1 or qty > 999:
            await _send_to_thread(
                source_message=message,
                text="Количество должно быть от 1 до 999.",
                thread_id=message.message_thread_id,
            )
            return

        _pending_qty_input.pop(key, None)
        cat = await session.get(Category, category_id)
        if cat is None:
            await message.answer("Категория не найдена")
            return

        await _forward_for_category(
            actor_tg_id=message.from_user.id,
            target_message=message,
            session=session,
            bot=bot,
            category_id=category_id,
            qty=qty,
            selected_hold="no_hold",
        )
    return


