from __future__ import annotations
import re
from html import escape
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.moderation_service import ModerationService
from src.services.user_service import UserService
from src.services.admin_service import AdminService
from src.database.models.enums import RejectionReason, SubmissionStatus
from src.database.models.category import Category
from src.utils.phone_norm import extract_and_normalize_phone
from src.callbacks.moderation import SimQueueCD
from src.utils.submission_media import bot_send_submission

router = Router(name="group-queue-router")

# Конфигурация чатов: chat_id -> {topic_id: action}
AUTO_FIX_CHATS: dict[int, dict[int, str]] = {
    -1003724834316: {
        76:  "blocked",       
        188: "not_a_scan",    
    },
}

_ACTION_PRESETS = {
    "blocked": (SubmissionStatus.BLOCKED, "Нарушение правил", "БЛОК"),
    "not_a_scan": (SubmissionStatus.NOT_A_SCAN, "Плохое качество", "НЕ СКАН"),
    "rejected": (SubmissionStatus.REJECTED, "Брак материала", "БРАК"),
}

@router.message(Command("sim"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_sim_start(message: Message, session: AsyncSession):
    """Показывает список категорий для выдачи в текущий топик."""
    if not await AdminService(session=session).is_admin(message.from_user.id): return
    
    mod_svc = ModerationService(session=session)
    queue = await mod_svc.get_pending_queue(limit=999)
    
    if not queue:
        return await message.answer("📭 <b>Очередь абсолютно пуста.</b>", parse_mode="HTML")
        
    # Группируем
    cats_data = {}
    for item in queue:
        cat_id = item.category_id
        if cat_id not in cats_data:
            cats_data[cat_id] = {"title": getattr(item.category, "title", "Unknown"), "count": 0}
        cats_data[cat_id]["count"] += 1
        
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    
    for cid, data in sorted(cats_data.items(), key=lambda x: x[1]["count"], reverse=True):
        btn_text = f"{data['title']} — {data['count']} шт."
        builder.button(text=btn_text, callback_data=SimQueueCD(action="cat", cat_id=cid).pack())
        
    builder.adjust(1)
    
    text = "📋 <b>Очередь активов</b>\n\nВыберите категорию для выдачи в эту тему:"
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(SimQueueCD.filter(F.action == "cat"))
async def cmd_sim_cat_selected(callback: CallbackQuery, callback_data: SimQueueCD, session: AsyncSession):
    """Выбор количества для выдачи после выбора категории."""
    cat = await session.get(Category, callback_data.cat_id)
    if not cat: return await callback.answer("Категория не найдена", show_alert=True)
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    presets = [1, 5, 10, 20, 50]
    
    for q in presets:
        builder.button(text=f"{q} шт.", callback_data=SimQueueCD(action="qty", cat_id=cat.id, val=str(q)).pack())
        
    builder.adjust(3, 2)
    text = f"📦 <b>{escape(cat.title)}</b>\n\nСколько симок отправить в этот чат?"
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(SimQueueCD.filter(F.action == "qty"))
async def cmd_sim_qty_selected(callback: CallbackQuery, callback_data: SimQueueCD, session: AsyncSession, bot: Bot):
    """Берет активы в работу и пересылает фото в топик."""
    qty = int(callback_data.val)
    admin = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    
    mod_svc = ModerationService(session=session)
    # 1. Забираем карточки конкретной категории
    items = await mod_svc.get_pending_queue(limit=qty)
    items_to_take = [i for i in items if i.category_id == callback_data.cat_id][:qty]
    
    if not items_to_take:
        return await callback.answer("Активы уже разобраны!", show_alert=True)
        
    taken_count = await mod_svc.take_specific_items_to_work(admin.id, [i.id for i in items_to_take])
    await session.commit()
    
    await callback.message.edit_text(f"🚀 Отправляю <b>{taken_count}</b> шт. в чат...", parse_mode="HTML")
    
    # 2. Отправляем фото в топик
    sent_count = 0
    chat_id = callback.message.chat.id
    thread_id = callback.message.message_thread_id
    
    for item in items_to_take:
        caption = f"ID: <code>{item.id}</code> | +{item.phone_normalized or '...'}"
        try:
            await bot_send_submission(
                bot, chat_id, item, caption, 
                **({"message_thread_id": thread_id} if thread_id else {})
            )
            sent_count += 1
        except Exception as e:
            pass # Игнорируем ошибки Telegram API при спаме
            
    await callback.message.answer(f"✅ Успешно выдано: <b>{sent_count}</b> шт.", parse_mode="HTML")

@router.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def auto_block_monitor(message: Message, session: AsyncSession):
    """Слушает сообщения в топиках. Если видит номер - применяет статус (Авто-блок)."""
    chat_id = message.chat.id
    topic_id = message.message_thread_id
    
    if chat_id not in AUTO_FIX_CHATS or topic_id not in AUTO_FIX_CHATS[chat_id]:
        return

    action_key = AUTO_FIX_CHATS[chat_id][topic_id]
    target_status, reason, label = _ACTION_PRESETS[action_key]
    
    raw_text = message.text.strip()
    norm_phone = extract_and_normalize_phone(raw_text)
    is_partial = False
    
    if not norm_phone:
        match = re.search(r"(?<!\d)(\d{4,9})(?!\d)", raw_text)
        if match:
            norm_phone = match.group(1)
            is_partial = True
            
    if not norm_phone: return

    mod_svc = ModerationService(session=session)
    changed_items = await mod_svc.auto_finalize_by_phone(
        phone_query=norm_phone, 
        status=target_status, 
        reason=reason, 
        comment=f"Авто-{label} из топика {topic_id}",
        is_partial=is_partial
    )
    await session.commit()
    
    if changed_items:
        display_phone = f"...{norm_phone}" if is_partial else f"+{norm_phone}"
        reply = f"⚠️ Номеру <b>{display_phone}</b> присвоен статус <b>{label}</b> ({len(changed_items)} шт.)."
        await message.reply(reply, parse_mode="HTML")