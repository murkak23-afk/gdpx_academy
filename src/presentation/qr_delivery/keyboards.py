"""Silver Sakura — Клавиатуры для выдачи QR-кодов."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from src.core.cache.keyboard_cache import cached_keyboard
from src.presentation.common.base import PremiumBuilder
from src.presentation.common.factory import QRDeliveryCD


@cached_keyboard(ttl=600)
def get_qr_delivery_main_kb(chat_id: int) -> InlineKeyboardMarkup:
    """Главное меню системы выдачи с привязкой к чату."""
    from aiogram.types import WebAppInfo
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

@cached_keyboard(ttl=120)
def get_qr_delivery_operators_kb(categories: list) -> InlineKeyboardMarkup:
    """Список операторов с количеством доступных симок."""
    builder = PremiumBuilder()
    for cat in categories:
        builder.button(f"📡 {cat['title']} ({cat['count']})", QRDeliveryCD(action="op_pick", val=str(cat['id'])))
    
    builder.row()
    builder.button("❮ НАЗАД", QRDeliveryCD(action="menu"))
    builder.adjust(1)
    return builder.as_markup()
