from __future__ import annotations
from aiogram.types import InlineKeyboardMarkup
from src.presentation.common.base import PremiumBuilder
from src.presentation.common.factory import AdminSupportCD, NavCD
from src.database.models.web_control import SupportTicket

def get_admin_tickets_kb(tickets: list[SupportTicket], page: int, total_count: int) -> InlineKeyboardMarkup:
    builder = PremiumBuilder()
    
    for t in tickets:
        status_icon = "🟢" if t.status == "open" else "✅" if t.status == "resolved" else "🔴"
        # Сокращаем тему для кнопки
        subj = t.subject[:20] + "..." if len(t.subject) > 20 else t.subject
        builder.button(
            text=f"{status_icon} #{t.id} | {subj}",
            callback_data=AdminSupportCD(action="view", ticket_id=t.id)
        )
    
    builder.adjust(1)
    
    # Пагинация (если нужна, пока упрощенно)
    
    builder.row()
    builder.button("🔄 ОБНОВИТЬ", AdminSupportCD(action="list", page=page))
    builder.back(NavCD(to="admin_menu"), "❮ НАЗАД")
    
    return builder.as_markup()

def get_admin_ticket_view_kb(ticket_id: int) -> InlineKeyboardMarkup:
    builder = PremiumBuilder()
    
    builder.button("✍️ ОТВЕТИТЬ", AdminSupportCD(action="reply", ticket_id=ticket_id))
    builder.button("🔒 ЗАКРЫТЬ ТИКЕТ", AdminSupportCD(action="close", ticket_id=ticket_id))
    
    builder.adjust(1)
    builder.back(AdminSupportCD(action="list"), "❮ К СПИСКУ")
    
    return builder.as_markup()
