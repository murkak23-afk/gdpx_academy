"""Silver Sakura — Клавиатуры для выдачи QR-кодов."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from src.keyboards.base import PremiumBuilder
from src.keyboards.factory import QRDeliveryCD

def get_qr_delivery_main_kb() -> InlineKeyboardMarkup:
    """Главное меню системы выдачи."""
    return (PremiumBuilder()
            .button("📱 ОПЕРАТОРЫ", QRDeliveryCD(action="op_list"))
            .row()
            .button("❌ ОТМЕНИТЬ ДЕЙСТВИЕ", QRDeliveryCD(action="cancel"))
            .adjust(1)
            .as_markup())

def get_qr_delivery_operators_kb(categories: list) -> InlineKeyboardMarkup:
    """Список операторов с количеством доступных симок."""
    builder = PremiumBuilder()
    for cat in categories:
        builder.button(f"📡 {cat['title']} ({cat['count']})", QRDeliveryCD(action="op_pick", val=str(cat['id'])))
    
    builder.row()
    builder.button("❮ НАЗАД", QRDeliveryCD(action="menu"))
    builder.adjust(1)
    return builder.as_markup()
