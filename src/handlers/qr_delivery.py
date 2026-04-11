# ruff: noqa: F401
from __future__ import annotations

import asyncio
import logging
import re
import random
import time
from html import escape
from datetime import datetime, timezone
from typing import Optional, List, Dict

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, InputMediaDocument
from aiogram.exceptions import TelegramRetryAfter
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from src.core.config import get_settings
from src.database.models.category import Category
from src.database.models.enums import SubmissionStatus, UserRole
from src.database.models.submission import Submission
from src.keyboards.base import PremiumBuilder
from src.keyboards.factory import QRDeliveryCD, AutoFixConfirmCD, NavCD
from src.keyboards.moderation import get_qr_delivery_main_kb, get_qr_delivery_operators_kb
from src.services.submission_service import SubmissionService
from src.services.user_service import UserService
from src.services.workflow_service import WorkflowService
from src.services.moderation_service import ModerationService
from src.states.qr_delivery import QRDeliveryStates
from src.utils.media import media
from src.utils.ui_builder import DIVIDER, DIVIDER_LIGHT
from src.utils.text_format import edit_message_text_or_caption_safe

router = Router(name="qr-delivery-router")
logger = logging.getLogger(__name__)

RANDOM_PHRASES = [
    "Продуктивного дня! 🔥",
    "Удачного сканирования! 🚀",
    "Пусть QR-коды залетают как родные! ⚡️",
    "Работаем в том же темпе! 💪",
    "Звонилки будут в восторге! 💎"
]


def _get_item_caption(item: Submission) -> str:
    """Генерирует премиальный шаблон подписи для актива."""
    return (
        f"🧧 <b>GDPX // QR DELIVERY</b>\n"
        f"📞 <b>{item.phone_normalized or '—'}</b>\n"
        f"🕒 {item.created_at.strftime('%d.%m %H:%M')}\n"
        f"{DIVIDER_LIGHT}\n"
        f"📝 <code>{escape(item.description_text or '—')}</code>"
    )


async def _explosive_send(item: Submission, message: Message, bot: Bot):
    """Отправка без ограничений с одной попыткой восстановления при Flood."""
    caption = _get_item_caption(item)
    thread_id = message.message_thread_id
    
    try:
        if item.attachment_type == "document":
            await bot.send_document(chat_id=message.chat.id, document=item.telegram_file_id, caption=caption, parse_mode="HTML", message_thread_id=thread_id, disable_notification=True)
        else:
            await bot.send_photo(chat_id=message.chat.id, photo=item.telegram_file_id, caption=caption, parse_mode="HTML", message_thread_id=thread_id, disable_notification=True)
        return True
    except TelegramRetryAfter as e:
        logger.warning(f"Flood hit on {item.phone_normalized}! Waiting {e.retry_after}s")
        await asyncio.sleep(e.retry_after)
        try:
            if item.attachment_type == "document":
                await bot.send_document(chat_id=message.chat.id, document=item.telegram_file_id, caption=caption, parse_mode="HTML", message_thread_id=thread_id)
            else:
                await bot.send_photo(chat_id=message.chat.id, photo=item.telegram_file_id, caption=caption, parse_mode="HTML", message_thread_id=thread_id)
            return True
        except Exception: return False
    except Exception as e:
        logger.error(f"Explosive send fail: {e}")
        return False


async def check_simbuyer_access(event: Message | CallbackQuery, session: AsyncSession) -> bool:
    user_svc = UserService(session=session)
    user = await user_svc.get_by_telegram_id(event.from_user.id)
    return user and user.role in (UserRole.SIMBUYER, UserRole.OWNER, UserRole.ADMIN)


@router.message(Command("qr"))
async def cmd_qr_root(message: Message, session: AsyncSession):
    if not await check_simbuyer_access(message, session): return
    stmt = select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING, Submission.is_archived == False)
    total = await session.scalar(stmt) or 0
    text = (f"🧧 <b>GDPX // ДОСТАВКА QR</b>\n{DIVIDER}\n📦 <b>В буфере:</b> <code>{total}</code> шт.\n\n<i>Выберите оператора для отгрузки:</i>")
    await message.answer(text, reply_markup=get_qr_delivery_main_kb(), parse_mode="HTML")


@router.callback_query(QRDeliveryCD.filter(F.action == "menu"))
async def cb_qr_menu(callback: CallbackQuery, session: AsyncSession):
    stmt = select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING, Submission.is_archived == False)
    total = await session.scalar(stmt) or 0
    text = (f"🧧 <b>GDPX // ДОСТАВКА QR</b>\n{DIVIDER}\n📦 <b>В буфере:</b> <code>{total}</code> шт.")
    banner = media.get("delivery.png")
    try:
        await callback.message.edit_media(media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"), reply_markup=get_qr_delivery_main_kb())
    except Exception: await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_qr_delivery_main_kb())
    await callback.answer()


@router.callback_query(QRDeliveryCD.filter(F.action == "op_list"))
async def cb_qr_op_list(callback: CallbackQuery, session: AsyncSession):
    stmt = select(Category).join(Submission, Category.id == Submission.category_id).where(Submission.status == SubmissionStatus.PENDING, Submission.is_archived == False).group_by(Category.id)
    cats = list((await session.execute(stmt)).scalars().all())
    if not cats: return await callback.answer("📭 Очередь пуста.", show_alert=True)
    text = (f"🧧 <b>GDPX // ВЫБОР КЛАСТЕРА</b>\n{DIVIDER}\nВыберите оператора:")
    banner = media.get("delivery_oper.png")
    try:
        await callback.message.edit_media(media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"), reply_markup=get_qr_delivery_operators_kb(cats))
    except Exception: await edit_message_text_or_caption_safe(callback.message, text, reply_markup=get_qr_delivery_operators_kb(cats))
    await callback.answer()


@router.callback_query(QRDeliveryCD.filter(F.action == "op_pick"))
async def cb_qr_op_pick(callback: CallbackQuery, callback_data: QRDeliveryCD, state: FSMContext):
    await state.update_data(qr_cat_id=int(callback_data.val))
    await state.set_state(QRDeliveryStates.waiting_for_count)
    text = (f"🧧 <b>GDPX // ПАРАМЕТРЫ ВЫДАЧИ</b>\n{DIVIDER}\n🔢 <b>Введите количество (1-100):</b>")
    banner = media.get("delivery_kolvo.png")
    kb = PremiumBuilder().back(QRDeliveryCD(action="op_list"), "❮ К СПИСКУ").as_markup()
    try:
        await callback.message.edit_media(media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"), reply_markup=kb)
    except Exception: await edit_message_text_or_caption_safe(callback.message, text, reply_markup=kb)
    await callback.answer()


@router.message(F.text.regexp(r"^\d+$"), QRDeliveryStates.waiting_for_count)
async def process_qr_delivery_count(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    """БЕЗОПАСНАЯ ЭКСТРЕМАЛЬНАЯ ОТГРУЗКА."""
    try:
        if not await check_simbuyer_access(message, session): return
        count = int(message.text)
        if not (1 <= count <= 100): return await message.answer("❌ Введите число от 1 до 100.")
        
        data = await state.get_data()
        cat_id = data.get("qr_cat_id")
        user_svc = UserService(session=session)
        db_user = await user_svc.get_by_telegram_id(message.from_user.id)
        
        # 1. Берем карточки (БЕЗ СМЕНЫ СТАТУСА В БД)
        stmt = select(Submission).where(
            Submission.category_id == cat_id, 
            Submission.status == SubmissionStatus.PENDING, 
            Submission.is_archived == False
        ).order_by(Submission.created_at.asc()).limit(count).with_for_update(skip_locked=True)
        items = list((await session.execute(stmt)).scalars().all())
        
        if not items:
            await state.clear()
            return await message.answer("📭 Очередь пуста.")

        await state.clear()
        start_total = time.time()

        async def _worker(item: Submission, idx: int):
            """Отправляет и меняет статус в БД ТОЛЬКО ПОСЛЕ УСПЕХА в Telegram."""
            await asyncio.sleep(idx * 0.03) # Микро-шаг 30мс для ровного старта
            if await _explosive_send(item, message, bot):
                # Статус меняем ФОНОМ, чтобы не тормозить отгрузку следующей симки
                asyncio.create_task(_background_audit(item.id, db_user.id, bot))
                return True
            return False

        # 2. ПАРАЛЛЕЛЬНЫЙ ЗАПУСК ВСЕХ ЗАДАЧ
        results = await asyncio.gather(*[_worker(items[i], i) for i in range(len(items))])
        sent_count = sum(1 for r in results if r)

        total_duration = time.time() - start_total
        phrase = random.choice(RANDOM_PHRASES)
        
        # Финальный отчет отправляем с небольшой паузой, так как лимит на чат мог быть исчерпан
        await asyncio.sleep(1.0)
        try:
            await message.answer(f"✅ <b>Отгрузка завершена за {total_duration:.1f} сек.</b>\nДоставлено: {sent_count} / {len(items)} шт.\n\n{phrase}", parse_mode="HTML")
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            await message.answer(f"✅ <b>Отгрузка завершена за {total_duration:.1f} сек.</b>\nДоставлено: {sent_count} / {len(items)} шт.\n\n{phrase}", parse_mode="HTML")
            
    except Exception as e:
        logger.exception(f"Error in Explosive-QR: {e}")
        await message.answer("⚠️ Ошибка при выдаче данных.")


@router.message(F.chat.type.in_(["group", "supergroup"]), F.message_thread_id.is_not(None))
async def process_topic_feedback(message: Message, session: AsyncSession, bot: Bot):
    """Авто-фиксация (БЛОК / НЕ СКАН)."""
    try:
        settings = get_settings()
        if not settings.auto_fix_enabled: return
        chat_config = settings.auto_fix_chats.get(message.chat.id)
        if not chat_config: return
        action_type = chat_config.get(message.message_thread_id)
        if not action_type: return 

        text = message.text or message.caption or ""
        raw_phones = re.findall(r"(?:^|[^\d])([789]\d{9,10})(?:[^\d]|$)", text)
        if not raw_phones: return

        wf_svc = WorkflowService(session=session)
        user_svc = UserService(session=session)
        db_admin = await user_svc.get_by_telegram_id(message.from_user.id)
        admin_id = db_admin.id if db_admin else 1
        target_status = SubmissionStatus.BLOCKED if action_type == "blocked" else SubmissionStatus.NOT_A_SCAN

        success_phones = []
        for raw in set(raw_phones):
            clean = raw[-10:]
            sub = found_p = None
            for p in [5, 4, 3]:
                suffix = clean[-p:]
                stmt = select(Submission).options(joinedload(Submission.category)).where(Submission.phone_normalized.like(f"%{suffix}"), Submission.status == SubmissionStatus.IN_WORK, Submission.is_archived == False).order_by(Submission.created_at.desc()).limit(1)
                sub = (await session.execute(stmt)).scalar_one_or_none()
                if sub: 
                    found_p = p
                    break
            
            if sub:
                if found_p >= 4:
                    await wf_svc.transition(submission_id=sub.id, admin_id=admin_id, to_status=target_status, rejection_reason="Auto-fix", comment=f"Topic {message.message_thread_id}", bot=bot)
                    success_phones.append(sub.phone_normalized)
                else:
                    cat = sub.category.title if sub.category else "—"
                    text_3 = (f"⚠️ <b>Найден номер по 3 цифрам:</b>\n\nПолный: <code>+{sub.phone_normalized}</code>\nКат: <code>{cat}</code>\n\nПодтверждаете?")
                    kb = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="✅ Да", callback_data=AutoFixConfirmCD(item_id=sub.id, status=action_type, action="confirm").pack()),
                        InlineKeyboardButton(text="❌ Нет", callback_data=AutoFixConfirmCD(item_id=sub.id, status=action_type, action="cancel").pack())
                    ]])
                    try: await message.reply(text_3, reply_markup=kb, parse_mode="HTML")
                    except Exception: pass

        if success_phones:
            await session.commit()
            label = "🚫 БЛОК" if action_type == "blocked" else "📵 НЕ СКАН"
            res = ", ".join([f"<code>{p}</code>" for p in success_phones])
            try: await message.reply(f"✅ <b>{label}:</b> {res}", parse_mode="HTML")
            except Exception: pass
    except Exception as e: logger.error(f"Auto-fix error: {e}")


@router.callback_query(AutoFixConfirmCD.filter())
async def cb_autofix_confirm(callback: CallbackQuery, callback_data: AutoFixConfirmCD, session: AsyncSession, bot: Bot):
    try:
        user_svc = UserService(session=session)
        db_admin = await user_svc.get_by_telegram_id(callback.from_user.id)
        if callback_data.action == "cancel":
            return await callback.message.edit_text("❌ <b>Отменено.</b>", parse_mode="HTML")
        target_status = SubmissionStatus.BLOCKED if callback_data.status == "blocked" else SubmissionStatus.NOT_A_SCAN
        wf_svc = WorkflowService(session=session)
        sub = await wf_svc.transition(submission_id=callback_data.item_id, admin_id=db_admin.id if db_admin else 1, to_status=target_status, rejection_reason="Auto-fix (confirmed)", comment="3 digits", bot=bot)
        if sub:
            await session.commit()
            label = "🚫 БЛОК" if callback_data.status == "blocked" else "📵 НЕ СКАН"
            await callback.message.edit_text(f"✅ <b>{label}:</b> <code>{sub.phone_normalized}</code>", parse_mode="HTML")
        else: await callback.answer("❌ Ошибка", show_alert=True)
    except Exception as e: logger.exception(f"Autofix error: {e}")


async def _background_audit(submission_id: int, admin_id: int, bot: Bot):
    from src.database.session import SessionFactory
    async with SessionFactory() as session:
        try:
            wf_svc = WorkflowService(session=session)
            await wf_svc.transition(submission_id=submission_id, admin_id=admin_id, to_status=SubmissionStatus.IN_WORK, comment="Выдано через /qr (Explosive)", bot=bot)
            await session.commit()
        except Exception as e: logger.error(f"Background audit error: {e}")
