"""Silver Sakura — Клавиатуры для выдачи QR-кодов."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, WebAppInfo, InlineKeyboardButton
from src.presentation.common.base import PremiumBuilder
from src.presentation.common.factory import QRDeliveryCD


def get_qr_delivery_main_kb() -> InlineKeyboardMarkup:
    """Классическое главное меню выдачи (только кнопки)."""
    return (PremiumBuilder()
            .button("📱 СПИСОК ОПЕРАТОРОВ", QRDeliveryCD(action="op_list"))
            .button("❌ ОТМЕНИТЬ ДЕЙСТВИЕ", QRDeliveryCD(action="cancel"))
            .adjust(1)
            .as_markup())

def get_qr_delivery_webapp_kb(chat_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для входа в Хаб (используем URL для совместимости с группами)."""
    from src.core.config import get_settings
    settings = get_settings()
    # Чистим базовый URL
    base_url = settings.webhook_url.split('/webhook')[0]
    webapp_url = f"{base_url}/delivery?chat_id={chat_id}"
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 ОТКРЫТЬ DELIVERY HUB", url=webapp_url)]
    ])

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
