"""FSM upload flow: category selection, photo/archive batch, CSV reporting."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    Document,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.keyboards import is_sell_esim_button, seller_main_inline_keyboard
from src.keyboards.callbacks import (
    CB_SELLER_BATCH_CSV_NO,
    CB_SELLER_BATCH_CSV_YES,
    CB_SELLER_BATCH_REJECT,
    CB_SELLER_BATCH_SEND,
    CB_SELLER_CANCEL_FSM,
    CB_SELLER_FINISH_BATCH,
    CB_SELLER_FSM_CAT,
    CB_SELLER_MENU_QUICK_ADD,
    CB_SELLER_MENU_SELL,
)
from src.services import (
    AdminService,
    CategoryService,
    SellerQuotaService,
    SubmissionService,
    UserService,
)
from src.states.submission_state import SubmissionState
from src.utils.fsm_progress import FSMProgressFormatter
from src.utils.submission_media import (
    ATTACHMENT_DOCUMENT,
    ATTACHMENT_PHOTO,
    is_allowed_archive_document,
)
from src.utils.text_format import edit_message_text_safe

from ._shared import (
    REJECT_DUPLICATE_BATCH,
    REJECT_NO_NUMBER,
    REJECT_NUMBER_WITHOUT_MEDIA,
    REJECT_BAD_FILE,
    _batch_accept,
    _batch_csv_choice_keyboard,
    _batch_csv_file,
    _batch_mark_seen_or_duplicate,
    _batch_reject,
    _batch_report_text,
    _captcha_keyboard,
    _normalize_phone_batch,
    _refresh_batch_status_message,
    _render_profile_text,
    _renderer,
    _route_admin_menu_from_seller_fsm,
    _route_start_from_seller_fsm,
    _is_admin_menu_shortcut,
    _is_start_shortcut,
    _safe_delete_message,
    _schedule_batch_idle_menu,
    _seller_fsm_cancel_keyboard,
    _seller_fsm_categories_keyboard,
    _send_fsm_step_message,
)

router = Router(name="seller-submission-router")


# ── Upload prechecks ──────────────────────────────────────────────────────


async def _upload_prechecks(
    user,
    submission_service: SubmissionService,
    state: FSMContext,
    message: Message,
    session: AsyncSession,
) -> bool:
    """Common guards before accepting a file. Returns True if upload can proceed."""
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


# ── Submission finalization ───────────────────────────────────────────────


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
    """Creates submission. When stay_in_batch=True stays on the photo step."""
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

    await SubmissionService(session=session).create_submission(
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
        dashboard = await SubmissionService(session=session).get_user_dashboard_stats(
            user_id=user.id
        )
        await message.answer(
            text=_renderer.render_user_profile(
                {
                    "username": user.username or "resident",
                    "user_id": user.telegram_id,
                    "approved_count": int(dashboard.get("accepted", 0)),
                    "pending_count": int(dashboard.get("pending", 0)),
                    "rejected_count": int(dashboard.get("rejected", 0)),
                },
                user.telegram_id,
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
    """Stores file hash in FSM and advances to the description step."""
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
        desc_text = FSMProgressFormatter.format_fsm_quick_message(current_step=3)
    else:
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


# ── Handlers ──────────────────────────────────────────────────────────────


@router.message(F.text.func(is_sell_esim_button))
async def on_sell_content(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Starts the FSM sale flow: category → photo → description."""
    categories = await CategoryService(session=session).get_active_categories()
    if not categories:
        await message.answer("Сейчас нет активных категорий. Попробуй позже.")
        return
    await state.set_state(SubmissionState.waiting_for_category)
    from src.utils.clean_screen import send_clean_text_screen

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
async def on_seller_menu_sell(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    categories = await CategoryService(session=session).get_active_categories()
    if not categories:
        await callback.answer("Сейчас нет активных категорий", show_alert=True)
        return
    await state.set_state(SubmissionState.waiting_for_category)
    await callback.answer()
    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            "Продать eSIM\n\nШаг 1/3: выбери категорию (оператора).\n"
            "После выбора сразу переходишь к загрузке симки.",
            reply_markup=_seller_fsm_categories_keyboard(categories),
        )


@router.callback_query(F.data == CB_SELLER_MENU_QUICK_ADD)
async def on_seller_menu_quick_add(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Quick add: category → photo → done (no separate description step)."""
    categories = await CategoryService(session=session).get_active_categories()
    if not categories:
        await callback.answer("Сейчас нет активных категорий", show_alert=True)
        return
    await state.set_state(SubmissionState.waiting_for_category)
    await state.update_data(quick_add=True)
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
async def on_seller_fsm_category_pick(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
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
            photo_text = FSMProgressFormatter.format_fsm_quick_message(current_step=2)
        else:
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
async def on_seller_cancel_fsm(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if callback.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return
    await state.clear()
    dashboard = await SubmissionService(session=session).get_user_dashboard_stats(
        user_id=user.id
    )
    text = _renderer.render_user_profile(
        {
            "username": user.username or "resident",
            "user_id": user.telegram_id,
            "approved_count": int(dashboard.get("accepted", 0)),
            "pending_count": int(dashboard.get("pending", 0)),
            "rejected_count": int(dashboard.get("rejected", 0)),
        },
        user.telegram_id,
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
async def on_seller_finish_batch(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if callback.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return

    await callback.answer("Фиксирую последние загрузки...")
    # Debounce: allow any in-flight batch messages to finish processing.
    await asyncio.sleep(3)

    data = await state.get_data()
    accepted = int(data.get("batch_accepted", 0))
    rejected = int(data.get("batch_rejected", 0))
    reasons = dict(data.get("batch_reject_reasons", {}))

    await state.update_data(
        batch_final_accepted=accepted,
        batch_final_rejected=rejected,
        batch_final_reasons=reasons,
    )
    await state.set_state(SubmissionState.waiting_for_batch_csv_choice)

    if callback.message is not None:
        await edit_message_text_safe(
            callback.message,
            _batch_report_text(accepted, rejected, reasons),
            parse_mode="HTML",
            reply_markup=_batch_csv_choice_keyboard(),
        )


@router.callback_query(
    F.data == CB_SELLER_BATCH_REJECT,
    StateFilter(SubmissionState.waiting_for_photo),
)
async def on_seller_batch_reject_request(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await state.set_state(SubmissionState.waiting_for_batch_delete_phone)
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            "Введи номер телефона для удаления из всей БХ (например, +79999999999).",
            reply_markup=_seller_fsm_cancel_keyboard(),
        )


@router.message(SubmissionState.waiting_for_batch_delete_phone, F.text)
async def on_seller_batch_delete_phone(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
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


@router.callback_query(
    F.data == CB_SELLER_BATCH_CSV_YES,
    StateFilter(SubmissionState.waiting_for_batch_csv_choice),
)
async def on_seller_batch_csv_yes(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if callback.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return
    data = await state.get_data()
    rows = list(data.get("batch_rows", []))
    await state.clear()

    dashboard = await SubmissionService(session=session).get_user_dashboard_stats(
        user_id=user.id
    )
    profile_text = _renderer.render_user_profile(
        {
            "username": user.username or "resident",
            "user_id": user.telegram_id,
            "approved_count": int(dashboard.get("accepted", 0)),
            "pending_count": int(dashboard.get("pending", 0)),
            "rejected_count": int(dashboard.get("rejected", 0)),
        },
        user.telegram_id,
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


@router.callback_query(
    F.data == CB_SELLER_BATCH_CSV_NO,
    StateFilter(SubmissionState.waiting_for_batch_csv_choice),
)
async def on_seller_batch_csv_no(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    if callback.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("Сначала /start", show_alert=True)
        return
    await state.clear()
    dashboard = await SubmissionService(session=session).get_user_dashboard_stats(
        user_id=user.id
    )
    profile_text = _renderer.render_user_profile(
        {
            "username": user.username or "resident",
            "user_id": user.telegram_id,
            "approved_count": int(dashboard.get("accepted", 0)),
            "pending_count": int(dashboard.get("pending", 0)),
            "rejected_count": int(dashboard.get("rejected", 0)),
        },
        user.telegram_id,
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
    """Handles text input during category selection step."""
    if message.text is None or message.from_user is None:
        return

    if _is_admin_menu_shortcut(message.text) and await AdminService(
        session=session
    ).is_admin(message.from_user.id):
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


@router.message(SubmissionState.waiting_for_photo, F.photo)
async def on_photo_received(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Validates limits and duplicates, then accepts the photo."""
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
    if await _batch_mark_seen_or_duplicate(
        state, phone=caption, file_unique_id=best_photo.file_unique_id
    ):
        await _batch_reject(state, reason_code=REJECT_DUPLICATE_BATCH, phone=caption)
        await _refresh_batch_status_message(message, state)
        _schedule_batch_idle_menu(message, state, message.from_user.id)
        return

    if await submission_service.is_duplicate_accepted(image_sha256=image_sha256):
        await UserService(session=session).set_duplicate_timeout(
            user_id=user.id, minutes=60
        )
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


@router.message(SubmissionState.waiting_for_photo, F.document)
async def on_archive_document_received(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Accepts archive documents."""
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
    if await _batch_mark_seen_or_duplicate(
        state, phone=caption, file_unique_id=document.file_unique_id
    ):
        await _batch_reject(state, reason_code=REJECT_DUPLICATE_BATCH, phone=caption)
        await _refresh_batch_status_message(message, state)
        _schedule_batch_idle_menu(message, state, message.from_user.id)
        return

    if await submission_service.is_duplicate_accepted(image_sha256=image_sha256):
        await UserService(session=session).set_duplicate_timeout(
            user_id=user.id, minutes=60
        )
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


@router.message(SubmissionState.waiting_for_photo)
async def on_photo_expected(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Hints at the expected format when something other than photo/archive arrives."""
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
    """Handles description step: currently rejects standalone text (expect photo+caption)."""
    if message.from_user is None or message.text is None:
        return
    await _safe_delete_message(message)

    if _is_start_shortcut(message.text):
        await _route_start_from_seller_fsm(message, state, session)
        return

    if _is_admin_menu_shortcut(message.text) and await AdminService(
        session=session
    ).is_admin(message.from_user.id):
        await _route_admin_menu_from_seller_fsm(message, state, session)
        return

    # New upload mode: only complete messages «media + phone» are accepted.
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
async def on_start_inside_submission_fsm(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Allows escaping seller FSM at any time via /start."""
    await _route_start_from_seller_fsm(message, state, session)


@router.message(SubmissionState.waiting_for_description)
async def on_description_expected(message: Message) -> None:
    """Hints at the expected format when non-text arrives at description step."""
    await message.answer(
        text=FSMProgressFormatter.format_fsm_quick_message(current_step=3),
        reply_markup=_seller_fsm_cancel_keyboard(),
        parse_mode="HTML",
    )
