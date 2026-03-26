from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Document, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.keyboards import (
    REPLY_BTN_BACK,
    categories_keyboard,
    is_admin_main_menu_text,
    is_sell_esim_button,
    match_admin_menu_canonical,
    moderation_item_keyboard,
    seller_main_menu_keyboard,
    seller_submission_step_keyboard,
)
from src.main_operators import MAIN_OPERATOR_GROUPS
from src.services import AdminService, CategoryService, SellerQuotaService, SubmissionService, UserService
from src.states import SubmissionState
from src.utils.submission_media import (
    ATTACHMENT_DOCUMENT,
    ATTACHMENT_PHOTO,
    bot_send_submission,
    is_allowed_archive_document,
)

router = Router(name="seller-router")
PHONE_DESCRIPTION_PATTERN = re.compile(r"^\+7\d{10}$")


def _format_seller_esim_stats(user, stats: dict) -> str:
    """Текст раздела «Статистика» для продавца eSIM."""

    nick = f"@{user.username}" if user.username else "нет username"
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


async def _route_admin_menu_from_seller_fsm(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Сбрасывает FSM продавца и открывает раздел админ-меню (chief admin)."""

    if message.text is None or message.from_user is None:
        return
    label = match_admin_menu_canonical(message.text)
    if label is None:
        return
    await state.clear()
    if label == "Запросы":
        from src.handlers.admin import open_requests_section

        await open_requests_section(message, state, session)
    elif label == "Очередь":
        from src.handlers.moderation import on_moderation_queue

        await on_moderation_queue(message, session)
    elif label == "В работе":
        from src.handlers.moderation import on_in_review_queue

        await on_in_review_queue(message, session)
    elif label == "Выплаты":
        from src.handlers.admin import on_daily_report

        await on_daily_report(message, session)
    elif label == "Рассылка":
        from src.handlers.admin import on_broadcast_start

        await on_broadcast_start(message, state, session)
    elif label == "Архив (7days)":
        from src.handlers.admin import on_archive_help

        await on_archive_help(message, session)
    elif label == "Статистика":
        from src.handlers.admin import on_admin_stats_menu

        await on_admin_stats_menu(message, state, session)


async def _seller_menu_kb(session: AsyncSession, telegram_id: int):
    """Главное меню селлера с учётом языка; если пользователь не найден — дефолт RU."""

    user = await UserService(session=session).get_by_telegram_id(telegram_id)
    if user is None:
        return seller_main_menu_keyboard()
    return seller_main_menu_keyboard(language=user.language, role=user.role)


def _captcha_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пройти капчу", callback_data="captcha:start")],
            [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data="captcha:cancel")],
        ]
    )


@router.message(F.text == REPLY_BTN_BACK, StateFilter(None))
async def on_reply_back_root(message: Message, session: AsyncSession) -> None:
    """«Назад» без активного FSM: главное меню селлера или админа."""

    if message.from_user is None:
        return
    if await AdminService(session=session).is_admin(message.from_user.id):
        user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
        if user is None:
            await message.answer("Сначала нажми /start.")
            return
        await message.answer(
            "Главное меню. Чтобы открыть админ-панель — кнопка «Войти в админ панель».",
            reply_markup=seller_main_menu_keyboard(language=user.language, role=user.role),
        )
        return
    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer("Сначала нажми /start.")
        return
    await message.answer("Главное меню.", reply_markup=seller_main_menu_keyboard(language=user.language, role=user.role))


@router.message(F.text == "Профиль")
async def on_profile(message: Message, session: AsyncSession) -> None:
    """Показывает базовые данные профиля пользователя."""

    if message.from_user is None:
        return

    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer("Сначала пройди регистрацию через /start.")
        return

    await message.answer(
        text=(
            f"Профиль:\n"
            f"ID: {user.telegram_id}\n"
            f"Username: @{user.username or 'нет'}\n"
            f"Язык: {user.language.value}\n"
            f"Роль: {user.role.value}"
        ),
        reply_markup=seller_main_menu_keyboard(language=user.language, role=user.role),
    )


@router.message(F.text == "Статистика")
async def on_stats(message: Message, session: AsyncSession) -> None:
    """Показывает дашборд статистики селлера."""

    if message.from_user is None:
        return

    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer("Сначала пройди регистрацию через /start.")
        return

    stats = await SubmissionService(session=session).get_user_esim_seller_stats(user_id=user.id)
    await message.answer(
        text=_format_seller_esim_stats(user, stats),
        reply_markup=seller_main_menu_keyboard(language=user.language, role=user.role),
    )


@router.message(F.text.func(is_sell_esim_button))
async def on_sell_content(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Стартует FSM-флоу продажи: категория -> фото -> описание."""

    categories = await CategoryService(session=session).get_active_categories()
    if not categories:
        await message.answer("Сейчас нет активных категорий. Попробуй позже.")
        return

    await state.set_state(SubmissionState.waiting_for_category)
    await message.answer(
        text="Выбери категорию:",
        reply_markup=categories_keyboard([category.title for category in categories]),
    )


@router.message(SubmissionState.waiting_for_category, F.text.in_({REPLY_BTN_BACK, "Отмена"}))
async def on_cancel_submission(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Отменяет создание карточки по запросу пользователя."""

    await state.clear()
    if message.from_user is None:
        await message.answer("Операция отменена.")
        return
    await message.answer(
        "Операция отменена.",
        reply_markup=await _seller_menu_kb(session, message.from_user.id),
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

    if match_admin_menu_canonical(message.text) is not None and await AdminService(session=session).is_admin(
        message.from_user.id
    ):
        await _route_admin_menu_from_seller_fsm(message, state, session)
        return

    text = message.text.strip()
    category = await CategoryService(session=session).get_by_title(text)
    if category is None:
        await message.answer(f"Выбери категорию кнопкой ниже или нажми «{REPLY_BTN_BACK}».")
        return

    await state.update_data(category_id=category.id)
    await state.set_state(SubmissionState.waiting_for_photo)
    await message.answer(
        text=(
            "Отправь материал:\n"
            "• фото (как картинку), или\n"
            "• архив одним файлом: zip, rar, 7z, tar, gz, bz2, xz и др.\n\n"
            "Если к фото или файлу добавить **подпись** строго в формате `+79999999999`, "
            "карточка уйдёт на модерацию сразу. Можно подряд несколько сообщений — "
            "каждое с подходящей подписью будет отдельным товаром.\n\n"
            "Архив отправляй **как файл** (документ), не как фото."
        ),
        reply_markup=seller_submission_step_keyboard(),
        parse_mode="Markdown",
    )


@router.message(SubmissionState.waiting_for_photo, F.text == REPLY_BTN_BACK)
async def on_back_from_photo(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Возврат к выбору категории."""

    if message.from_user is None:
        return
    categories = await CategoryService(session=session).get_active_categories()
    if not categories:
        await state.clear()
        await message.answer("Нет активных категорий.", reply_markup=await _seller_menu_kb(session, message.from_user.id))
        return
    await state.clear()
    await state.set_state(SubmissionState.waiting_for_category)
    await message.answer(
        "Выбери категорию:",
        reply_markup=categories_keyboard([c.title for c in categories]),
    )


@router.message(SubmissionState.waiting_for_description, F.text == REPLY_BTN_BACK)
async def on_back_from_description(message: Message, state: FSMContext) -> None:
    """Возврат к шагу загрузки файла."""

    await state.update_data(
        telegram_file_id=None,
        file_unique_id=None,
        image_sha256=None,
        attachment_type=ATTACHMENT_PHOTO,
    )
    await state.set_state(SubmissionState.waiting_for_photo)
    await message.answer(
        "Отправь **один** материал снова:\n"
        "• фото (как картинку), или\n"
        "• архив одним файлом.\n\n"
        "Архив — **файлом** (документ), не как фото.",
        reply_markup=seller_submission_step_keyboard(),
        parse_mode="Markdown",
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
        await message.answer("У тебя временное ограничение. Подтверди, что ты человек.", reply_markup=_captcha_keyboard())
        return False
    if user.duplicate_timeout_until and user.duplicate_timeout_until > datetime.now(timezone.utc):
        await state.clear()
        await message.answer(
            f"Временный таймаут за дубликаты до {user.duplicate_timeout_until}.",
            reply_markup=seller_main_menu_keyboard(language=user.language, role=user.role),
        )
        return False
    data = await state.get_data()
    raw_cid = data.get("category_id")
    if raw_cid is None:
        await state.clear()
        await message.answer(
            "Сначала выбери категорию (подтип оператора).",
            reply_markup=seller_main_menu_keyboard(language=user.language, role=user.role),
        )
        return False
    category_id = int(raw_cid)

    quota_svc = SellerQuotaService(session=session)
    daily_limit = await quota_svc.get_quota_for_today(user.id, category_id)
    if daily_limit <= 0:
        await state.clear()
        await message.answer(
            "На сегодня в этой категории не назначен запрос на выгрузку. Администратор задаёт лимиты в разделе «Запросы».",
            reply_markup=seller_main_menu_keyboard(language=user.language, role=user.role),
        )
        return False
    counts = await submission_service.get_daily_counts_by_category_for_user(user_id=user.id)
    daily_count = counts.get(category_id, 0)
    if daily_count >= daily_limit:
        await state.clear()
        await message.answer(
            f"Достигнут дневной лимит по запросу в этой категории: {daily_limit}. Новые материалы — завтра (UTC) или после смены запроса.",
            reply_markup=seller_main_menu_keyboard(language=user.language, role=user.role),
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
    """Создаёт submission и уведомляет админов. При stay_in_batch остаёмся на шаге «фото» для следующей карточки."""

    category_service = CategoryService(session=session)
    selected_category = await category_service.get_by_id(category_id)
    if selected_category is None:
        await state.clear()
        await message.answer(
            "Категория не найдена. Начни заново.",
            reply_markup=seller_main_menu_keyboard(language=user.language, role=user.role),
        )
        return False
    if selected_category.total_upload_limit is not None:
        current_total = await category_service.get_total_uploaded_count(selected_category.id)
        if current_total >= selected_category.total_upload_limit:
            await state.clear()
            await message.answer(
                f"По категории достигнут общий лимит: {selected_category.total_upload_limit}.",
                reply_markup=seller_main_menu_keyboard(language=user.language, role=user.role),
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

    admin_users = await UserService(session=session).get_all_admins()
    kind_label = "архив (файл)" if submission.attachment_type == ATTACHMENT_DOCUMENT else "фото"
    notify_text = (
        f"Новый материал на проверку ({kind_label})\n"
        f"Submission #{submission.id}\n"
        f"Продавец: @{user.username or 'без_username'}\n"
        f"Seller internal ID: {submission.user_id}\n"
        f"Категория ID: {submission.category_id}\n"
        f"Описание: {submission.description_text[:300]}"
    )
    for admin_user in admin_users:
        try:
            await bot_send_submission(
                bot,
                admin_user.telegram_id,
                submission,
                notify_text,
                reply_markup=moderation_item_keyboard(submission_id=submission.id),
            )
        except TelegramAPIError:
            continue

    if stay_in_batch:
        await state.update_data(
            telegram_file_id=None,
            file_unique_id=None,
            image_sha256=None,
            attachment_type=ATTACHMENT_PHOTO,
        )
        await state.set_state(SubmissionState.waiting_for_photo)
        await message.answer(
            text=(
                "Материал отправлен на модерацию. Можешь отправить ещё фото или архив "
                "(удобно с подписью +79999999999 в том же сообщении — сразу на модерацию) "
                f"или нажми «{REPLY_BTN_BACK}», чтобы сменить категорию."
            ),
            reply_markup=seller_submission_step_keyboard(),
        )
    else:
        await state.clear()
        await message.answer(
            text="Материал отправлен на модерацию. Спасибо!",
            reply_markup=seller_main_menu_keyboard(language=user.language, role=user.role),
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
    file_bytes: bytes,
    attachment_type: str,
) -> None:
    """Сохраняет хэш и переводит на шаг описания."""

    image_sha256 = hashlib.sha256(file_bytes).hexdigest()

    if await submission_service.is_duplicate_accepted(image_sha256=image_sha256):
        await UserService(session=session).set_duplicate_timeout(user_id=user.id, minutes=60)
        await state.clear()
        await message.answer(
            "Этот материал уже был принят ранее. Выдан таймаут 60 минут и ограничение до прохождения капчи.",
            reply_markup=seller_main_menu_keyboard(language=user.language, role=user.role),
        )
        return

    await state.update_data(
        telegram_file_id=file_id,
        file_unique_id=file_unique_id,
        image_sha256=image_sha256,
        attachment_type=attachment_type,
    )
    await state.set_state(SubmissionState.waiting_for_description)
    await message.answer(
        "Отлично. Теперь отправь описание в формате номера: +79999999999.",
        reply_markup=seller_submission_step_keyboard(),
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
    file_info = await bot.get_file(best_photo.file_id)
    file_stream = await bot.download_file(file_info.file_path)
    image_bytes = file_stream.read()
    image_sha256 = hashlib.sha256(image_bytes).hexdigest()

    caption = (message.caption or "").strip()
    if caption and PHONE_DESCRIPTION_PATTERN.fullmatch(caption):
        if await submission_service.is_duplicate_accepted(image_sha256=image_sha256):
            await UserService(session=session).set_duplicate_timeout(user_id=user.id, minutes=60)
            await state.clear()
            await message.answer(
                "Этот материал уже был принят ранее. Выдан таймаут 60 минут и ограничение до прохождения капчи.",
                reply_markup=seller_main_menu_keyboard(language=user.language, role=user.role),
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
    if caption:
        await message.answer(
            "Подпись к фото не в формате номера +79999999999 (ровно +7 и 10 цифр). "
            "Отправь номер **отдельным сообщением** ниже.",
            parse_mode="Markdown",
            reply_markup=seller_submission_step_keyboard(),
        )

    await _store_file_and_ask_description(
        state=state,
        message=message,
        session=session,
        submission_service=submission_service,
        user=user,
        file_id=best_photo.file_id,
        file_unique_id=best_photo.file_unique_id,
        file_bytes=image_bytes,
        attachment_type=ATTACHMENT_PHOTO,
    )


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

    document: Document = message.document
    if not is_allowed_archive_document(document):
        await message.answer(
            "Пришли архив известного формата (zip, rar, 7z, tar, gz, …) **файлом**.\n"
            "Или отправь фото как картинку.",
            parse_mode="Markdown",
            reply_markup=seller_submission_step_keyboard(),
        )
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

    file_info = await bot.get_file(document.file_id)
    file_stream = await bot.download_file(file_info.file_path)
    raw = file_stream.read()
    image_sha256 = hashlib.sha256(raw).hexdigest()

    caption = (message.caption or "").strip()
    if caption and PHONE_DESCRIPTION_PATTERN.fullmatch(caption):
        if await submission_service.is_duplicate_accepted(image_sha256=image_sha256):
            await UserService(session=session).set_duplicate_timeout(user_id=user.id, minutes=60)
            await state.clear()
            await message.answer(
                "Этот материал уже был принят ранее. Выдан таймаут 60 минут и ограничение до прохождения капчи.",
                reply_markup=seller_main_menu_keyboard(language=user.language, role=user.role),
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
    if caption:
        await message.answer(
            "Подпись к файлу не в формате номера +79999999999 (ровно +7 и 10 цифр). "
            "Отправь номер **отдельным сообщением** ниже.",
            parse_mode="Markdown",
            reply_markup=seller_submission_step_keyboard(),
        )

    await _store_file_and_ask_description(
        state=state,
        message=message,
        session=session,
        submission_service=submission_service,
        user=user,
        file_id=document.file_id,
        file_unique_id=document.file_unique_id,
        file_bytes=raw,
        attachment_type=ATTACHMENT_DOCUMENT,
    )


@router.message(SubmissionState.waiting_for_photo)
async def on_photo_expected(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Подсказывает формат шага, если пришло не фото и не архив."""

    if (
        message.text
        and message.from_user is not None
        and is_admin_main_menu_text(message.text)
        and await AdminService(session=session).is_admin(message.from_user.id)
    ):
        await _route_admin_menu_from_seller_fsm(message, state, session)
        return

    await message.answer(
        "Нужно отправить **фото** или **один архив файлом** (zip, rar, 7z, …). "
        "Несколько товаров подряд — отдельными сообщениями; у каждого может быть подпись +79999999999. "
        "В одном альбоме Telegram — только одна подпись на всю группу, для разных номеров шли по одному фото.",
        parse_mode="Markdown",
        reply_markup=seller_submission_step_keyboard(),
    )


@router.message(SubmissionState.waiting_for_description, F.text)
async def on_description_received(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Сохраняет карточку после получения описания."""

    if message.from_user is None or message.text is None:
        return

    if is_admin_main_menu_text(message.text) and await AdminService(session=session).is_admin(message.from_user.id):
        await _route_admin_menu_from_seller_fsm(message, state, session)
        return

    data = await state.get_data()
    category_id = data.get("category_id")
    telegram_file_id = data.get("telegram_file_id")
    file_unique_id = data.get("file_unique_id")
    image_sha256 = data.get("image_sha256")
    attachment_type = str(data.get("attachment_type", ATTACHMENT_PHOTO))
    if not all([category_id, telegram_file_id, file_unique_id, image_sha256]):
        await state.clear()
        await message.answer(
            "Сессия устарела. Начни заново через «Продать eSIM».",
            reply_markup=await _seller_menu_kb(session, message.from_user.id),
        )
        return

    user = await UserService(session=session).get_by_telegram_id(message.from_user.id)
    if user is None:
        await state.clear()
        await message.answer("Сначала пройди регистрацию через /start.")
        return

    description_text = message.text.strip()
    if not PHONE_DESCRIPTION_PATTERN.fullmatch(description_text):
        await message.answer(
            "Описание должно быть только в формате номера: +79999999999.\n"
            "Отправь описание повторно строго в этом формате.",
            reply_markup=seller_submission_step_keyboard(),
        )
        return

    await _finalize_submission_after_upload(
        message=message,
        state=state,
        session=session,
        bot=bot,
        user=user,
        category_id=int(category_id),
        telegram_file_id=str(telegram_file_id),
        file_unique_id=str(file_unique_id),
        image_sha256=str(image_sha256),
        attachment_type=attachment_type,
        description_text=description_text,
        stay_in_batch=False,
    )


@router.message(SubmissionState.waiting_for_description)
async def on_description_expected(message: Message) -> None:
    """Подсказывает формат шага, если пришел не текст."""

    await message.answer(
        "Сейчас нужно отправить текстовое описание.",
        reply_markup=seller_submission_step_keyboard(),
    )


@router.callback_query(F.data == "captcha:cancel")
async def on_captcha_cancel(callback: CallbackQuery, session: AsyncSession) -> None:
    """Снимает inline-капчу и возвращает главное меню."""

    if callback.from_user is None:
        return
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
    kb = (
        seller_main_menu_keyboard(language=user.language, role=user.role)
        if user is not None
        else seller_main_menu_keyboard()
    )
    if callback.message is not None:
        await callback.message.answer("Главное меню.", reply_markup=kb)


@router.callback_query(F.data == "captcha:start")
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
            "Введи код ниже отдельным сообщением:\n"
            f"{answer}\n\n"
            "Это упрощенная captcha для снятия ограничения.",
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
        await message.answer(
            "Ограничение снято. Можно продолжать работу.",
            reply_markup=seller_main_menu_keyboard(language=user.language, role=user.role),
        )
        return
    await message.answer("Неверный код. Нажми 'Пройти капчу' и попробуй снова.", reply_markup=_captcha_keyboard())
