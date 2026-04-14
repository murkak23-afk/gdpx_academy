"""Silver Sakura — Клавиатуры для выдачи QR-кодов."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, WebAppInfo
from src.presentation.common.base import PremiumBuilder
from src.presentation.common.factory import QRDeliveryCD


def get_qr_delivery_main_kb(chat_id: int) -> InlineKeyboardMarkup:
    """Главное меню системы выдачи с привязкой к чату. (БЕЗ КЭША для стабильности)"""
    from src.core.config import get_settings
    settings = get_settings()
    
    # URL нашего приложения + передаем ID текущего чата
    base_url = settings.webhook_url.replace('/webhook', '')
    webapp_url = f"{base_url}/delivery?chat_id={chat_id}"
    
    return (PremiumBuilder()
            .button("📱 ОПЕРАТОРЫ (КНОПКИ)", QRDeliveryCD(action="op_list"))
            .button("🌐 DELIVERY HUB (APP)", web_app=WebAppInfo(url=webapp_url))
            .button("❌ ОТМЕНИТЬ ДЕЙСТВИЕ", QRDeliveryCD(action="cancel"))
            .adjust(1)
            .as_markup())

def get_qr_delivery_operators_kb(categories: list) -> InlineKeyboardMarkup:
    """Список операторов с количеством доступных симок."""
    builder = PremiumBuilder()
    for cat in categories:
        cat_id = cat['id'] if isinstance(cat, dict) else cat.id
        title = cat['title'] if isinstance(cat, dict) else cat.title
        count = cat['count'] if isinstance(cat, dict) else getattr(cat, 'count', 0)
        
        builder.button(f"📡 {title} ({count})", QRDeliveryCD(action="op_pick", val=str(cat_id)))
    
    builder.row()
    builder.button("❮ НАЗАД", QRDeliveryCD(action="menu"))
    builder.adjust(1)
    return builder.as_markup()
