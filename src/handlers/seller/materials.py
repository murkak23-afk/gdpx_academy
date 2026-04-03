"""Material management handlers: listing, pagination, editing, deletion."""

from __future__ import annotations

import hashlib

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.enums import SubmissionStatus
from src.database.models.submission import Submission
from src.keyboards import seller_main_inline_keyboard
from src.keyboards.callbacks import (
    CB_NOOP,
    CB_SELLER_CANCEL_FSM,
    CB_SELLER_MAT_BACK,
    CB_SELLER_MAT_CAT,
    CB_SELLER_MAT_DELETE,
    CB_SELLER_MAT_DELETE_CONFIRM,
    CB_SELLER_MAT_EDIT,
    CB_SELLER_MAT_EDIT_MEDIA,
    CB_SELLER_MAT_FILTER,
    CB_SELLER_MAT_ITEM,
    CB_SELLER_MAT_PAGE,
    CB_SELLER_MENU_MATERIAL,
)
from src.services import SubmissionService, UserService
from src.states.submission_state import SubmissionState
from src.utils.clean_screen import send_clean_text_screen
from src.utils.phone_norm import PHONE_NORM_ERROR_HTML, normalize_phone_strict
from src.utils.submission_media import (
    ATTACHMENT_DOCUMENT,
    ATTACHMENT_PHOTO,
    bot_send_submission,
    is_allowed_archive_document,
)
from src.utils.text_format import edit_message_text_safe

from ._shared import (
    MATERIAL_FILTER_ALL,
    MATERIAL_FILTER_ORDER,
    SELLER_DELETABLE_STATUSES,
    SELLER_PAGE_SIZE,
)

router = Router(name="seller-materials-router")


# ── Local keyboard and helper functions ───────────────────────────────────


def _seller_material_nav_keyboard(
    category_id: int, page: int, total: int
) -> InlineKeyboardMarkup:
    max_page = (max(total, 1) - 1) // SELLER_PAGE_SIZE
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"{CB_SELLER_MAT_PAGE}:{category_id}:{page - 1}",
            )
        )
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{max_page + 1}", callback_data=CB_NOOP))
    if page < max_page:
        nav.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"{CB_SELLER_MAT_PAGE}:{category_id}:{page + 1}",
            )
        )
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
    if filter_key == "active":
        return [SubmissionStatus.PENDING, SubmissionStatus.IN_REVIEW]
    if filter_key == "credit":
        return [SubmissionStatus.ACCEPTED]
    if filter_key == "debit":
        return [
            SubmissionStatus.REJECTED,
            SubmissionStatus.BLOCKED,
            SubmissionStatus.NOT_A_SCAN,
        ]
    return None


def _material_filter_label(filter_key: str) -> str:
    return {
        MATERIAL_FILTER_ALL: "Все",
        "active": "В работе",
        "credit": "Зачёт",
        "debit": "Незачёт",
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
                    callback_data=(
                        f"{CB_SELLER_MAT_ITEM}:{item.id}:{category_id}:{page}:{filter_key}"
                    ),
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

    nav_rows = _seller_material_nav_keyboard(
        category_id=category_id, page=page, total=total
    ).inline_keyboard
    if nav_rows:
        nav_row = nav_rows[0]
        for i, button in enumerate(nav_row):
            if button.callback_data and button.callback_data.startswith(
                f"{CB_SELLER_MAT_PAGE}:"
            ):
                nav_row[i] = InlineKeyboardButton(
                    text=button.text,
                    callback_data=f"{button.callback_data}:{filter_key}",
                )
        rows.append(nav_row)

    rows.append(
        [InlineKeyboardButton(text="⬅️ К списку операторов", callback_data=CB_SELLER_MAT_BACK)]
    )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


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
    items, total = await SubmissionService(
        session=session
    ).list_user_material_by_category_paginated(
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
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ К списку операторов",
                            callback_data=CB_SELLER_MAT_BACK,
                        )
                    ]
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
    await send_clean_text_screen(
        trigger_message=message,
        text=text,
        key=f"seller:material:category:{category_id}",
        reply_markup=keyboard,
    )


# ── Handlers ──────────────────────────────────────────────────────────────


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
        rows.append(
            [InlineKeyboardButton(text=text, callback_data=f"{CB_SELLER_MAT_CAT}:{f['category_id']}")]
        )
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
        rows.append(
            [InlineKeyboardButton(text=text, callback_data=f"{CB_SELLER_MAT_CAT}:{f['category_id']}")]
        )
    await edit_message_text_safe(
        callback.message,
        "Материал по операторам:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
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
        items, total = await SubmissionService(
            session=session
        ).list_user_material_by_category_paginated(
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
                        [
                            InlineKeyboardButton(
                                text="⬅️ К списку операторов",
                                callback_data=CB_SELLER_MAT_BACK,
                            )
                        ]
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
        items, total = await SubmissionService(
            session=session
        ).list_user_material_by_category_paginated(
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
                        [
                            InlineKeyboardButton(
                                text="⬅️ К списку операторов",
                                callback_data=CB_SELLER_MAT_BACK,
                            )
                        ]
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
    items, total = await SubmissionService(
        session=session
    ).list_user_material_by_category_paginated(
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
                        [
                            InlineKeyboardButton(
                                text="⬅️ К списку операторов",
                                callback_data=CB_SELLER_MAT_BACK,
                            )
                        ]
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
        await callback.answer()
        if callback.message is not None:
            await edit_message_text_safe(
                callback.message,
                "Материалов пока нет.",
                reply_markup=seller_main_inline_keyboard(),
            )
        return
    rows = []
    for f in folders:
        text = f"{f['title']} ({f['total']})"
        rows.append(
            [InlineKeyboardButton(text=text, callback_data=f"{CB_SELLER_MAT_CAT}:{f['category_id']}")]
        )
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
    submission_id, category_id, page, filter_key = _parse_material_item_callback(
        callback.data
    )
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
                    callback_data=(
                        f"{CB_SELLER_MAT_EDIT}:{submission.id}:{category_id}:{page}:{filter_key}"
                    ),
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
                    callback_data=(
                        f"{CB_SELLER_MAT_DELETE}:{submission.id}:{category_id}:{page}:{filter_key}"
                    ),
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
async def on_material_item_edit_start(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
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
    if (
        submission is None
        or submission.user_id != user.id
        or submission.status != SubmissionStatus.PENDING
    ):
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
        await callback.message.answer(
            "Отправь новый номер в формате +79999999999",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="❌ Отменить операцию", callback_data=CB_SELLER_CANCEL_FSM
                        )
                    ]
                ]
            ),
        )


@router.callback_query(F.data.startswith(f"{CB_SELLER_MAT_EDIT_MEDIA}:"))
async def on_material_item_edit_media_start(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if callback.from_user is None or callback.data is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return
    _, _, _, submission_id_raw = callback.data.split(":")
    submission = await session.get(Submission, int(submission_id_raw))
    if (
        submission is None
        or submission.user_id != user.id
        or submission.status != SubmissionStatus.PENDING
    ):
        await callback.answer("Обновление медиа доступно только для pending", show_alert=True)
        return
    await state.set_state(SubmissionState.waiting_for_material_edit_media)
    await state.update_data(material_edit_submission_id=int(submission_id_raw))
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            "Отправь новое фото или архив-файл для симки.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="❌ Отменить операцию", callback_data=CB_SELLER_CANCEL_FSM
                        )
                    ]
                ]
            ),
        )


@router.message(SubmissionState.waiting_for_material_edit_description, F.text)
async def on_material_item_edit_submit(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
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
    updated = await SubmissionService(
        session=session
    ).update_submission_description_for_seller(
        submission_id=submission_id,
        user_id=user.id,
        new_description=description_text,
    )
    await state.clear()
    if updated is None:
        await message.answer(
            "Не удалось обновить симку (только pending).",
            reply_markup=seller_main_inline_keyboard(),
        )
        return
    await message.answer(
        f"Симка #{updated.id} обновлена.",
        reply_markup=seller_main_inline_keyboard(),
    )


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
    await message.answer(
        "Медиа обновлено." if updated else "Не удалось обновить (только pending).",
        reply_markup=seller_main_inline_keyboard(),
    )


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
    await message.answer(
        "Медиа обновлено." if updated else "Не удалось обновить (только pending).",
        reply_markup=seller_main_inline_keyboard(),
    )


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
                                f"{CB_SELLER_MAT_DELETE_CONFIRM}:{submission_id_raw}:"
                                f"{category_id_raw}:{page_raw}:{filter_key}"
                            ),
                        )
                    ]
                ]
            ),
        )


@router.callback_query(F.data.startswith(f"{CB_SELLER_MAT_DELETE_CONFIRM}:"))
async def on_material_item_delete_confirm(
    callback: CallbackQuery, session: AsyncSession
) -> None:
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
