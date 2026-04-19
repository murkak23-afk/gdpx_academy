from __future__ import annotations
import logging
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from sqlalchemy import select, desc
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from src.presentation.common.factory import AdminSupportCD, NavCD
from src.services.support_service import SupportService
from src.presentation.admin_panel.support.keyboards import get_admin_tickets_kb, get_admin_ticket_view_kb
from src.core.utils.message_manager import MessageManager
from src.core.utils.ui_builder import DIVIDER, DIVIDER_LIGHT
from src.presentation.filters.admin import IsAdminFilter
from src.domain.users.user_service import UserService
from src.database.models.web_control import SupportTicket
from src.presentation.common.base import PremiumBuilder
from aiogram.fsm.state import State, StatesGroup

class AdminSupportState(StatesGroup):
    waiting_for_reply = State()

router = Router(name="admin-support-router")
logger = logging.getLogger(__name__)

@router.callback_query(AdminSupportCD.filter(F.action == "list"))
@router.message(Command("tickets"))
async def show_tickets_list(event: Message | CallbackQuery, session: AsyncSession, ui: MessageManager):
    """Список тикетов. Админы видят OPEN, Овнеры — ВСЮ ИСТОРИЮ."""
    try:
        from src.domain.users.user_service import UserService
        user_svc = UserService(session)
        user = await user_svc.get_by_telegram_id(event.from_user.id)
        if not user or user.role not in ["admin", "owner"]:
            return
            
        support_svc = SupportService(session)
        is_owner = user.role == "owner"
        
        if is_owner:
            tickets, total = await support_svc.get_all_tickets(limit=15)
            title = "📚 GDPX // ПОЛНАЯ ИСТОРИЯ ТИКЕТОВ"
        else:
            tickets = await support_svc.get_open_tickets()
            total = len(tickets)
            title = "📥 GDPX // SUPPORT TICKETS"
            
        text = (
            f"{title}\n"
            f"{DIVIDER}\n"
            f"📊 <b>Всего записей:</b> <code>{total}</code> шт.\n"
            f"{DIVIDER_LIGHT}"
        )
        
        if not tickets:
            text += "\n<i>✨ Нет записей в истории.</i>"
            
        kb = get_admin_tickets_kb(tickets, page=0, total_count=total)
        
        await ui.display(event=event, text=text, reply_markup=kb)
        if isinstance(event, CallbackQuery):
            await event.answer()
    except Exception as e:
        logger.exception(f"Error in show_tickets_list: {e}")

@router.callback_query(AdminSupportCD.filter(F.action == "view"))
async def view_ticket_detail(callback: CallbackQuery, callback_data: AdminSupportCD, session: AsyncSession, ui: MessageManager):
    """Детальный просмотр тикета с историей админа."""
    try:
        support_svc = SupportService(session)
        # Подгружаем с учетом assigned_admin для истории
        from sqlalchemy.orm import joinedload
        from src.database.models.web_control import SupportTicket
        stmt = (
            select(SupportTicket)
            .options(joinedload(SupportTicket.creator), joinedload(SupportTicket.assigned_admin))
            .where(SupportTicket.id == callback_data.ticket_id)
        )
        ticket = (await session.execute(stmt)).scalar_one_or_none()
        
        if not ticket:
            return await callback.answer("❌ Тикет не найден", show_alert=True)
            
        messages = await support_svc.get_ticket_messages(ticket.id)
        
        status_icon = "🟢" if ticket.status == "open" else "✅" if ticket.status == "resolved" else "🔴"
        creator_name = ticket.creator.username or f"ID:{ticket.creator.telegram_id}"
        admin_name = "<i>Ожидает...</i>"
        if ticket.assigned_admin:
            admin_name = f"@{ticket.assigned_admin.username}" if ticket.assigned_admin.username else f"ID:{ticket.assigned_admin.telegram_id}"

        text = (
            f"🎫 <b>ТИКЕТ #{ticket.id}</b> | {status_icon}\n"
            f"{DIVIDER}\n"
            f"👤 <b>Селлер:</b> @{creator_name}\n"
            f"📝 <b>Вопрос:</b> <code>{ticket.subject}</code>\n"
            f"👮 <b>Админ:</b> {admin_name}\n"
            f"📅 <b>Время:</b> <code>{ticket.created_at.strftime('%d.%m %H:%M:%S')}</code>\n"
            f"{DIVIDER_LIGHT}\n"
        )
        
        # Полная история сообщений
        for msg in messages:
            time_str = msg.created_at.strftime("%H:%M")
            if msg.sender.role in ["admin", "owner"]:
                sender_label = "👮"
            else:
                sender_label = "👤"
                
            text += f"[{time_str}] {sender_label} <b>{msg.sender.username or msg.sender.telegram_id}:</b> {msg.text}\n"
            
        kb = get_admin_ticket_view_kb(ticket.id)
        await ui.display(event=callback, text=text, reply_markup=kb)
        await callback.answer()
    except Exception as e:
        logger.exception(f"Error in view_ticket_detail: {e}")

@router.callback_query(AdminSupportCD.filter(F.action == "reply"), IsAdminFilter())
async def on_reply_ticket_start(callback: CallbackQuery, callback_data: AdminSupportCD, state: FSMContext, ui: MessageManager):
    """Переход в режим ожидания ответа."""
    await state.update_data(reply_ticket_id=callback_data.ticket_id)
    await state.set_state(AdminSupportState.waiting_for_reply)
    
    text = (
        f"✍️ <b>ОТВЕТ НА ТИКЕТ #{callback_data.ticket_id}</b>\n"
        f"{DIVIDER}\n"
        f"Введите ваше сообщение. Оно будет доставлено селлеру в бот.\n\n"
        f"<i>Поддерживается HTML-разметка.</i>"
    )
    
    from src.presentation.common.base import PremiumBuilder
    kb = PremiumBuilder().cancel(AdminSupportCD(action="view", ticket_id=callback_data.ticket_id), "ОТМЕНА").as_markup()
    
    await ui.display(event=callback, text=text, reply_markup=kb)
    await callback.answer()

@router.message(AdminSupportState.waiting_for_reply, F.text)
async def on_reply_message_receive(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    """Прием и отправка ответа селлеру."""
    try:
        logger.info(f"Admin/Owner {message.from_user.id} sending reply to ticket")
        data = await state.get_data()
        ticket_id = data.get("reply_ticket_id")
        
        from src.domain.users.user_service import UserService
        user_svc = UserService(session)
        admin = await user_svc.get_by_telegram_id(message.from_user.id)
        
        if not admin or admin.role not in ["admin", "owner"]:
            logger.warning(f"Unauthorized reply attempt by {message.from_user.id}")
            return
            
        support_svc = SupportService(session)
        ticket = await support_svc.get_ticket_by_id(ticket_id)
        
        if not ticket:
            await message.answer("❌ Тикет не найден. Возможно, он был удален.")
            await state.clear()
            return
            
        # Добавляем сообщение в БД
        await support_svc.add_message(ticket_id, admin.id, message.text)
        await session.commit()
        
        # Обновляем уведомление в админ-чате
        from src.core.notification_service import NotificationService
        from src.core.config import get_settings
        notif_svc = NotificationService(bot, get_settings())
        messages_all = await support_svc.get_ticket_messages(ticket.id)
        
        await notif_svc.notify_new_ticket(
            ticket=ticket,
            user_name=ticket.creator.username or str(ticket.creator.telegram_id),
            messages=messages_all
        )
        await session.commit()
        
        # Уведомляем селлера
        seller_text = (
            f"📩 <b>НОВОЕ СООБЩЕНИЕ ОТ ПОДДЕРЖКИ</b>\n"
            f"{DIVIDER}\n"
            f"<b>Тикет #{ticket.id}:</b> <code>{ticket.subject}</code>\n"
            f"{DIVIDER_LIGHT}\n"
            f"{message.text}\n"
            f"{DIVIDER_LIGHT}\n"
            f"<i>Вы можете ответить в разделе «Поддержка» главного меню.</i>"
        )
        
        try:
            from src.core.utils.message_manager import MessageManager
            mm = MessageManager(bot)
            await mm.send_notification(user_id=ticket.creator.telegram_id, text=seller_text)
        except Exception as e:
            logger.error(f"Failed to notify seller {ticket.creator.telegram_id}: {e}")
            
        await message.answer(f"✅ Ответ в тикет #{ticket.id} успешно отправлен.")
        await state.clear()
        
        # Возвращаемся в тикет
        # (Опционально: можно показать список тикетов)
        
    except Exception as e:
        logger.exception(f"Error in on_reply_message_receive: {e}")
        await message.answer("❌ Произошла ошибка при отправке ответа.")

@router.callback_query(AdminSupportCD.filter(F.action == "close"), IsAdminFilter())
async def on_close_ticket(callback: CallbackQuery, callback_data: AdminSupportCD, session: AsyncSession, ui: MessageManager):
    """Закрытие тикета."""
    try:
        support_svc = SupportService(session)
        success = await support_svc.close_ticket(callback_data.ticket_id)
        
        if success:
            await callback.answer("✅ Тикет успешно закрыт и перемещен в архив.", show_alert=True)
            await session.commit()
            await show_tickets_list(callback, session, ui)
        else:
            await callback.answer("❌ Ошибка при закрытии тикета.", show_alert=True)
    except Exception as e:
        logger.exception(f"Error in on_close_ticket: {e}")
