from __future__ import annotations

import re
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.enums import ContentType
from aiogram.filters import Command, or_f
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.submission import Submission
from src.database.models.user import User
from src.database.models.enums import RejectionReason, SubmissionStatus
from src.keyboards.admin_hints import HINT_IN_REVIEW, HINT_QUEUE
from src.keyboards import (
    CALLBACK_INLINE_BACK,
    REPLY_BTN_BACK,
    admin_main_menu_keyboard,
    forward_target_reply_keyboard,
    match_admin_menu_canonical,
    moderation_item_keyboard,
    moderation_reject_template_keyboard,
    moderation_review_keyboard,
    moderation_seller_group_keyboard,
    pagination_keyboard,
)
from src.core.config import get_settings
from src.services import (
    AdminAuditService,
    AdminChatForwardStatsService,
    AdminService,
    SubmissionService,
    UserService,
)
from src.states import AdminBatchPickState, AdminModerationForwardState
from src.utils.forward_target import target_chat_id_from_forward_pick
from src.utils.submission_media import bot_send_submission, message_answer_submission

router = Router(name="moderation-router")
PAGE_SIZE = 5


def _reply_is_queue(t: str | None) -> bool:
    return match_admin_menu_canonical(t) == "Очередь"


def _reply_is_in_review(t: str | None) -> bool:
    return match_admin_menu_canonical(t) == "В работе"


def _encode_queue_filters(seller_id: int | None, category_id: int | None, date_from: datetime | None) -> str:
    """Кодирует фильтры очереди в query-поле callback_data без двоеточий."""

    def _v(v: int | None) -> str:
        return str(v) if v is not None else ""

    def _d(v: datetime | None) -> str:
        if v is None:
            return ""
        return v.date().isoformat()  # YYYY-MM-DD (без ':')

    # Используем '|' и '=' чтобы не ломать split(":", 3) в обработчике.
    return f"s={_v(seller_id)}|c={_v(category_id)}|d={_d(date_from)}"


def _decode_queue_filters(raw: str | None) -> tuple[int | None, int | None, datetime | None]:
    if not raw:
        return None, None, None

    seller_id: int | None = None
    category_id: int | None = None
    date_from: datetime | None = None

    # Ожидаем формат: s=...|c=...|d=...
    parts = [p.strip() for p in raw.split("|") if p.strip()]
    for part in parts:
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        v = v.strip()
        if k == "s" and v.isdigit():
            seller_id = int(v)
        elif k == "c" and v.isdigit():
            category_id = int(v)
        elif k == "d" and v:
            try:
                # Берём только дату (UTC-наблюдение), чтобы не ловить время/таймзону.
                date_from = datetime.fromisoformat(v)
            except ValueError:
                continue

    return seller_id, category_id, date_from


@router.callback_query(F.data == CALLBACK_INLINE_BACK)
async def on_inline_back(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Убирает inline-клавиатуру и возвращает reply-меню админа."""

    if callback.from_user is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer("Меню администратора ниже.", reply_markup=admin_main_menu_keyboard())


@router.callback_query(F.data.startswith("mod:rejtpl_back:"))
async def on_reject_template_back(callback: CallbackQuery, session: AsyncSession) -> None:
    """Возврат с выбора причины отклонения к кнопкам карточки."""

    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    submission_id = int(callback.data.split(":")[2])
    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=moderation_item_keyboard(submission_id=submission_id))


def _format_pending_list_for_pick(pending: list[Submission]) -> str:
    """Список ID и короткого описания для выбора части пачки."""

    lines: list[str] = []
    for s in pending:
        lines.append(f"#{s.id} — {s.description_text[:100]}")
    text = "\n".join(lines)
    if len(text) > 3500:
        return text[:3490] + "\n…"
    return text


def _parse_submission_id_selection(text: str, pending_by_id: dict[int, Submission]) -> list[int]:
    """Парсит номера submission: перечисление и диапазоны «3-12» (включительно), только из pending."""

    ids: list[int] = []
    seen: set[int] = set()
    for raw in re.split(r"[\s,;]+", text.strip()):
        if not raw:
            continue
        if re.match(r"^\d+\s*-\s*\d+$", raw):
            a, b = re.split(r"\s*-\s*", raw, maxsplit=1)
            lo, hi = int(a), int(b)
            if lo > hi:
                lo, hi = hi, lo
            for i in range(lo, hi + 1):
                if i in pending_by_id and i not in seen:
                    seen.add(i)
                    ids.append(i)
            continue
        if raw.isdigit():
            n = int(raw)
            if n in pending_by_id and n not in seen:
                seen.add(n)
                ids.append(n)
    pending_sorted = sorted(pending_by_id.keys())
    return sorted(ids, key=lambda x: pending_sorted.index(x))


def _format_queue_card_caption(
    *,
    seller_label: str,
    submission_id: int,
    items_count: int,
    description_text: str,
    desc_max_len: int = 300,
) -> str:
    """Текст под товаром в разделе «Очередь» (админ-панель)."""

    desc = description_text[:desc_max_len] if description_text else "—"
    return (
        f"— Владелец: {seller_label}\n"
        f"— Индивидуальный ID товара: #{submission_id} (по нему поиск и действия)\n"
        f"— Товаров в очереди именно за этим владельцем: {items_count}\n"
        f"— Описание: {desc}"
    )


def _parse_filters(text: str | None) -> tuple[int | None, int | None, datetime | None]:
    if not text:
        return None, None, None
    seller_id = None
    category_id = None
    date_from = None
    for token in text.split():
        if token.startswith("seller=") and token.split("=", 1)[1].isdigit():
            seller_id = int(token.split("=", 1)[1])
        if token.startswith("category=") and token.split("=", 1)[1].isdigit():
            category_id = int(token.split("=", 1)[1])
        if token.startswith("date="):
            try:
                date_from = datetime.fromisoformat(token.split("=", 1)[1])
            except ValueError:
                continue
    return seller_id, category_id, date_from


@router.message(Command("moderation"))
@router.message(F.text.func(_reply_is_queue))
async def on_moderation_queue(message: Message, session: AsyncSession) -> None:
    """Показывает очередь pending, сгруппированную по продавцам."""

    if message.from_user is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    seller_id, category_id, date_from = _parse_filters(message.text)
    filters_query = _encode_queue_filters(seller_id=seller_id, category_id=category_id, date_from=date_from)
    groups, total = await SubmissionService(session=session).list_pending_groups_by_user_paginated(
        page=0,
        page_size=PAGE_SIZE,
        seller_id=seller_id,
        category_id=category_id,
        date_from=date_from,
    )
    if not groups:
        await message.answer("Очередь пустая.", reply_markup=admin_main_menu_keyboard())
        return

    first_card = True
    for seller_user_id, items_count in groups:
        seller = await session.get(User, seller_user_id)
        seller_nickname = f"@{seller.username}" if seller is not None and seller.username else "без username"
        sample_items = await SubmissionService(session=session).list_pending_submissions_by_user(user_id=seller_user_id)
        if not sample_items:
            continue
        sample = sample_items[0]
        cap = _format_queue_card_caption(
            seller_label=seller_nickname,
            submission_id=sample.id,
            items_count=items_count,
            description_text=sample.description_text,
        )
        if first_card:
            cap = f"{HINT_QUEUE}\n\n{cap}"
            first_card = False
        await message_answer_submission(
            message,
            sample,
            caption=cap,
            reply_markup=moderation_seller_group_keyboard(user_id=seller_user_id),
        )
    # Пагинация должна оставаться одним сообщением и обновляться при переходах.
    await message.answer(
        " ",
        reply_markup=pagination_keyboard(
            "mod:queue_page",
            page=0,
            total=total,
            page_size=PAGE_SIZE,
            query=filters_query,
        ),
    )


@router.callback_query(F.data.startswith("mod:queue_page:"))
async def on_queue_page(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    _, _, page_raw, query_raw = callback.data.split(":", 3)
    page = max(int(page_raw), 0)
    seller_id, category_id, date_from = _decode_queue_filters(query_raw)
    groups, total = await SubmissionService(session=session).list_pending_groups_by_user_paginated(
        page=page,
        page_size=PAGE_SIZE,
        seller_id=seller_id,
        category_id=category_id,
        date_from=date_from,
    )
    if callback.message is not None:
        # Обновляем существующее сообщение пагинации, чтобы не плодить “Навигация …”
        await callback.message.edit_text(
            " ",
            reply_markup=pagination_keyboard(
                "mod:queue_page",
                page=page,
                total=total,
                page_size=PAGE_SIZE,
                query=_encode_queue_filters(seller_id=seller_id, category_id=category_id, date_from=date_from),
            ),
        )
        first_card = True
        for seller_user_id, items_count in groups:
            seller = await session.get(User, seller_user_id)
            seller_nickname = f"@{seller.username}" if seller is not None and seller.username else "без username"
            sample_items = await SubmissionService(session=session).list_pending_submissions_by_user(user_id=seller_user_id)
            if not sample_items:
                continue
            sample = sample_items[0]
            cap = _format_queue_card_caption(
                seller_label=seller_nickname,
                submission_id=sample.id,
                items_count=items_count,
                description_text=sample.description_text,
            )
            if page == 0 and first_card:
                cap = f"{HINT_QUEUE}\n\n{cap}"
                first_card = False
            await message_answer_submission(
                callback.message,
                sample,
                caption=cap,
                reply_markup=moderation_seller_group_keyboard(user_id=seller_user_id),
            )
    await callback.answer()


@router.callback_query(F.data.startswith("mod:take_pick:"))
async def on_take_pick_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Старт выбора части карточек по ID перед пересылкой."""

    if callback.from_user is None or callback.data is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    seller_user_id = int(callback.data.split(":")[2])
    pending = await SubmissionService(session=session).list_pending_submissions_by_user(user_id=seller_user_id)
    if not pending:
        await callback.answer("У продавца нет pending-материалов", show_alert=True)
        return

    await state.set_state(AdminBatchPickState.waiting_for_submission_ids)
    await state.update_data(seller_user_id=seller_user_id)
    await callback.answer()
    list_text = _format_pending_list_for_pick(pending)
    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data="mod:pick_cancel")]]
    )
    await callback.message.answer(  # type: ignore[union-attr]
        "Укажи, какие товары переслать в чат или ЛС (по **индивидуальному ID** из списка).\n\n"
        "Примеры:\n"
        "• `101, 102, 105` — три конкретных номера\n"
        "• `3-12` — все pending с ID от 3 до 12 включительно (если в очереди есть 3, 6, 9 — уйдут все, что попали в диапазон)\n"
        "• можно комбинировать: `100-105, 200`\n\n"
        "После выбора бот попросит цель (группа / канал / ЛС). Остальные карточки продавца останутся в очереди.\n\n"
        f"Список:\n{list_text}",
        parse_mode="Markdown",
        reply_markup=cancel_kb,
    )
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data == "mod:pick_cancel")
async def on_pick_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена режима выбора ID."""

    await state.clear()
    await callback.answer("Отменено")
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer("Выбор отменён.", reply_markup=admin_main_menu_keyboard())


@router.message(AdminBatchPickState.waiting_for_submission_ids, F.text)
async def on_batch_pick_ids_received(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Принимает список ID и предлагает выбрать чат для частичной пересылки."""

    if message.from_user is None or message.text is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await state.clear()
        await message.answer("Недостаточно прав.")
        return

    data = await state.get_data()
    seller_user_id = int(data["seller_user_id"])
    pending = await SubmissionService(session=session).list_pending_submissions_by_user(user_id=seller_user_id)
    pending_by_id = {s.id: s for s in pending}

    valid_ids = _parse_submission_id_selection(message.text, pending_by_id)

    if not valid_ids:
        await message.answer(
            "Ни один из указанных ID не найден в pending у этого продавца. "
            "Проверь номера или диапазон и отправь снова.",
        )
        return

    await state.update_data(picked_submission_ids=valid_ids)
    await state.set_state(AdminModerationForwardState.waiting_for_target)
    await message.answer(
        f"Выбрано карточек: {len(valid_ids)}.\n\n"
        "Теперь выбери группу, канал или пользователя для ЛС:",
        reply_markup=forward_target_reply_keyboard(),
    )


@router.message(
    AdminModerationForwardState.waiting_for_target,
    or_f(F.content_type == ContentType.CHAT_SHARED, F.content_type == ContentType.USER_SHARED),
)
async def on_moderation_forward_target_shared(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Пересылает пачку или выбранные карточки в выбранный чат или ЛС."""

    if message.from_user is None:
        return
    if not await AdminService(session=session).is_admin(message.from_user.id):
        await state.clear()
        return

    target_chat_id = target_chat_id_from_forward_pick(message)
    if target_chat_id is None:
        await message.answer("Используй кнопки выбора группы, канала или пользователя.")
        return

    data = await state.get_data()
    seller_user_id = int(data["seller_user_id"])
    picked_ids_for_audit = list(data.get("picked_submission_ids", []))
    if not picked_ids_for_audit:
        await state.clear()
        await message.answer(
            "Не выбраны карточки. Начни с очереди.",
            reply_markup=admin_main_menu_keyboard(),
        )
        return

    pending = await SubmissionService(session=session).list_pending_submissions_by_user(user_id=seller_user_id)
    id_set = set(picked_ids_for_audit)
    submissions = [s for s in pending if s.id in id_set]

    if not submissions:
        await state.clear()
        await message.answer(
            "Подходящих карточек в pending больше нет.",
            reply_markup=admin_main_menu_keyboard(),
        )
        return

    admin_user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if admin_user is None:
        await state.clear()
        await message.answer("Админ не найден в БД.", reply_markup=admin_main_menu_keyboard())
        return

    seller = await session.get(User, seller_user_id)
    seller_nickname = f"@{seller.username}" if seller is not None and seller.username else "без username"
    sent_count = 0
    for item in submissions:
        await bot_send_submission(
            bot,
            target_chat_id,
            item,
            caption=f"{item.description_text}\n\nПродавец: {seller_nickname}",
        )
        sent_count += 1

    if sent_count > 0:
        await AdminChatForwardStatsService(session=session).add_forwards_for_telegram_chat(
            target_chat_id,
            sent_count,
        )

    marked = await SubmissionService(session=session).mark_submissions_in_review(submissions=submissions, admin_id=admin_user.id)
    await state.clear()

    await AdminAuditService(session=session).log(
        admin_id=admin_user.id,
        action="take_partial_batch",
        target_type="user",
        target_id=seller_user_id,
        details=(
            f"chat_id={target_chat_id}, submission_ids={picked_ids_for_audit}, sent={sent_count}, marked={marked}"
        ),
    )
    await message.answer(
        f"Переслано: {sent_count}. В работу: {marked}. Остальные pending остались в очереди.",
        reply_markup=admin_main_menu_keyboard(),
    )


@router.message(Command("in_review"))
@router.message(F.text.func(_reply_is_in_review))
async def on_in_review_queue(message: Message, session: AsyncSession) -> None:
    """Показывает карточки, взятые админом в работу."""

    if message.from_user is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.is_admin(message.from_user.id):
        await message.answer("Недостаточно прав.")
        return

    admin_user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if admin_user is None:
        await message.answer("Пользователь не найден в БД.")
        return

    seller_id, category_id, date_from = _parse_filters(message.text)
    items, total = await SubmissionService(session=session).list_in_review_submissions_paginated(
        admin_id=admin_user.id,
        page=0,
        page_size=PAGE_SIZE,
        seller_id=seller_id,
        category_id=category_id,
        date_from=date_from,
    )
    if not items:
        await message.answer("У тебя нет карточек в работе.", reply_markup=admin_main_menu_keyboard())
        return

    first_card = True
    for item in items:
        seller = await session.get(User, item.user_id)
        seller_nickname = f"@{seller.username}" if seller is not None and seller.username else "без username"
        cap = (
            f"Submission #{item.id}\n"
            f"Продавец: {seller_nickname}\n"
            f"Seller internal ID: {item.user_id}\n"
            f"Описание: {item.description_text[:300]}"
        )
        if first_card:
            cap = f"{HINT_IN_REVIEW}\n\n{cap}"
            first_card = False
        await message_answer_submission(
            message,
            item,
            caption=cap,
            reply_markup=moderation_review_keyboard(submission_id=item.id),
        )
    await message.answer(
        "Навигация по разделу 'В работе':",
        reply_markup=pagination_keyboard("mod:in_review_page", page=0, total=total, page_size=PAGE_SIZE),
    )


@router.callback_query(F.data.startswith("mod:in_review_page:"))
async def on_in_review_page(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.data is None:
        return
    admin = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin is None:
        await callback.answer("Админ не найден", show_alert=True)
        return
    _, _, page_raw, _ = callback.data.split(":", 3)
    page = max(int(page_raw), 0)
    items, total = await SubmissionService(session=session).list_in_review_submissions_paginated(
        admin_id=admin.id,
        page=page,
        page_size=PAGE_SIZE,
    )
    if callback.message is not None:
        first_card = True
        for item in items:
            seller = await session.get(User, item.user_id)
            seller_nickname = f"@{seller.username}" if seller is not None and seller.username else "без username"
            cap = (
                f"Submission #{item.id}\n"
                f"Продавец: {seller_nickname}\n"
                f"Seller internal ID: {item.user_id}\n"
                f"Описание: {item.description_text[:300]}"
            )
            if page == 0 and first_card:
                cap = f"{HINT_IN_REVIEW}\n\n{cap}"
                first_card = False
            await message_answer_submission(
                callback.message,
                item,
                caption=cap,
                reply_markup=moderation_review_keyboard(submission_id=item.id),
            )
        await callback.message.answer(
            "Навигация:",
            reply_markup=pagination_keyboard("mod:in_review_page", page=page, total=total, page_size=PAGE_SIZE),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("mod:forward_cancel"))
async def on_forward_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Отменяет выбор чата пересылки."""

    await state.clear()
    await callback.answer("Отменено")
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer("Возврат в админ-меню.", reply_markup=admin_main_menu_keyboard())


@router.callback_query(F.data.startswith("mod:take:"))
async def on_take_to_work(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Совместимость: кнопка для одиночного товара, переводим на пачку продавца."""

    if callback.from_user is None or callback.data is None:
        return

    submission_id = int(callback.data.split(":")[2])
    submission = await session.get(Submission, submission_id)
    if submission is None:
        await callback.answer("Карточка не найдена", show_alert=True)
        return

    pending_items = await SubmissionService(session=session).list_pending_submissions_by_user(user_id=submission.user_id)
    if not pending_items:
        await callback.answer("У продавца нет pending-материалов", show_alert=True)
        return

    await state.set_state(AdminModerationForwardState.waiting_for_target)
    await state.update_data(
        seller_user_id=submission.user_id,
        picked_submission_ids=[submission_id],
    )

    await callback.answer()
    await bot.send_message(
        chat_id=callback.from_user.id,
        text="Выбери группу, канал или пользователя для ЛС — куда переслать этот товар:",
        reply_markup=forward_target_reply_keyboard(),
    )
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("mod:reject:"))
async def on_reject(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Отклоняет карточку и уведомляет автора."""

    if callback.from_user is None or callback.data is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    submission_id = int(callback.data.split(":")[2])
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            "Выбери причину отклонения:",
            reply_markup=moderation_reject_template_keyboard(submission_id=submission_id),
        )


@router.callback_query(F.data.startswith("mod:rejtpl:"))
async def on_reject_template(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
) -> None:
    if callback.from_user is None or callback.data is None:
        return
    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await callback.answer("Пользователь не найден в БД", show_alert=True)
        return
    _, _, submission_id_raw, reason_key = callback.data.split(":")
    submission_id = int(submission_id_raw)
    reasons = {
        "duplicate": (RejectionReason.DUPLICATE, "Дубликат материала"),
        "quality": (RejectionReason.QUALITY, "Низкое качество"),
        "rules": (RejectionReason.RULES_VIOLATION, "Нарушение правил"),
        "other": (RejectionReason.OTHER, "Отклонено админом"),
    }
    reason, comment = reasons.get(reason_key, (RejectionReason.OTHER, "Отклонено админом"))
    submission = await SubmissionService(session=session).reject_submission(
        submission_id=submission_id,
        admin_id=admin_user.id,
        reason=reason,
        comment=comment,
    )
    if submission is None:
        await callback.answer("Карточка уже обработана", show_alert=True)
        return
    await AdminAuditService(session=session).log(
        admin_id=admin_user.id,
        action="reject_submission",
        target_type="submission",
        target_id=submission.id,
        details=comment,
    )
    seller = await session.get(User, submission.user_id)
    if seller is not None:
        await bot.send_message(chat_id=seller.telegram_id, text=f"Материал #{submission.id} отклонен. Причина: {comment}")
    await callback.answer("Отклонено")


@router.callback_query(F.data.startswith("mod:accept:"))
async def on_accept(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    """Принимает карточку, начисляет сумму и архивирует материал."""

    if callback.from_user is None or callback.data is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    submission_id = int(callback.data.split(":")[2])
    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await callback.answer("Пользователь не найден в БД", show_alert=True)
        return

    submission_obj = await session.get(Submission, submission_id)
    if submission_obj is None:
        await callback.answer("Карточка не найдена", show_alert=True)
        return
    if submission_obj.status != SubmissionStatus.IN_REVIEW:
        await callback.answer("Карточка уже обработана", show_alert=True)
        return

    submission_service = SubmissionService(session=session)
    settings = get_settings()
    archive_text = (
        f"ACCEPTED\n"
        f"submission_id: {submission_obj.id}\n"
        f"user_id: {submission_obj.user_id}\n"
        f"description: {submission_obj.description_text}"
    )
    if settings.archive_chat_id == 0:
        await callback.answer("Не задан ARCHIVE_CHAT_ID в .env", show_alert=True)
        return
    archive_message = await bot_send_submission(
        bot,
        settings.archive_chat_id,
        submission_obj,
        archive_text,
    )

    accepted = await submission_service.accept_submission(
        submission_id=submission_id,
        admin_id=admin_user.id,
        archive_chat_id=settings.archive_chat_id,
        archive_message_id=archive_message.message_id,
    )
    if accepted is None:
        await callback.answer("Карточка уже обработана", show_alert=True)
        return
    await AdminAuditService(session=session).log(
        admin_id=admin_user.id,
        action="accept_submission",
        target_type="submission",
        target_id=accepted.id,
        details=f"amount={accepted.accepted_amount}",
    )

    seller = await session.get(User, accepted.user_id)
    if seller is not None:
        seller_nickname = f"@{seller.username}" if seller.username else "без username"
        await bot.send_message(
            chat_id=seller.telegram_id,
            text=(
                f"Материал #{accepted.id} принят. Начислено: {accepted.accepted_amount} USDT.\n"
                f"Продавец: {seller_nickname}"
            ),
        )

    await callback.answer("Принято и зачислено")
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("mod:block:"))
async def on_block(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    """Финально отклоняет карточку со статусом blocked."""

    await _handle_final_reject(
        callback=callback,
        session=session,
        bot=bot,
        to_status=SubmissionStatus.BLOCKED,
        reason=RejectionReason.RULES_VIOLATION,
        user_text="Материал заблокирован (нарушение правил).",
    )


@router.callback_query(F.data.startswith("mod:notscan:"))
async def on_not_a_scan(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    """Финально отклоняет карточку со статусом not_a_scan."""

    await _handle_final_reject(
        callback=callback,
        session=session,
        bot=bot,
        to_status=SubmissionStatus.NOT_A_SCAN,
        reason=RejectionReason.QUALITY,
        user_text="Материал отклонен: это не скан/неподходящий формат.",
    )


async def _handle_final_reject(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
    to_status: SubmissionStatus,
    reason: RejectionReason,
    user_text: str,
) -> None:
    """Общий обработчик финального отклонения."""

    if callback.from_user is None or callback.data is None:
        return

    admin_service = AdminService(session=session)
    if not await admin_service.is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return

    submission_id = int(callback.data.split(":")[2])
    admin_user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if admin_user is None:
        await callback.answer("Пользователь не найден в БД", show_alert=True)
        return

    submission = await SubmissionService(session=session).final_reject_submission(
        submission_id=submission_id,
        admin_id=admin_user.id,
        to_status=to_status,
        reason=reason,
        comment=user_text,
    )
    if submission is None:
        await callback.answer("Карточка уже обработана", show_alert=True)
        return
    await AdminAuditService(session=session).log(
        admin_id=admin_user.id,
        action="final_reject_submission",
        target_type="submission",
        target_id=submission.id,
        details=user_text,
    )

    seller = await session.get(User, submission.user_id)
    if seller is not None:
        seller_nickname = f"@{seller.username}" if seller.username else "без username"
        await bot.send_message(
            chat_id=seller.telegram_id,
            text=f"Материал #{submission.id}: {user_text}\nПродавец: {seller_nickname}",
        )

    await callback.answer("Статус обновлен")
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
