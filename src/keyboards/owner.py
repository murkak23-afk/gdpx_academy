"""Silver Sakura — Клавиатуры владельца (Owner/Admin)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from src.keyboards.base import PremiumBuilder
from src.keyboards.constants import *
from src.keyboards.factory import CatConCD, CatManageCD, NavCD

def get_moderator_main_kb() -> InlineKeyboardMarkup:
    """Главное меню Модератора (только работа с eSIM)."""
    from src.keyboards.factory import AdminMenuCD
    return (PremiumBuilder()
            .primary("⚖️ МОДЕРАЦИЯ", AdminMenuCD(section="moderation"))
            .button("🔍 ГЛОБАЛЬНЫЙ ПОИСК", "mod_search")
            .adjust(1)
            .as_markup())

def get_owner_main_kb() -> InlineKeyboardMarkup:
    """Главное меню Владельца (Полный контроль)."""
    return (PremiumBuilder()
            .button("🏯 Командный центр", "owner_cmd_center")
            .button("💎 Выплаты и финансы", "owner_finance")
            .button("📈 Аналитика и статистика", "owner_stats")
            .button("🏷️ Категории и ставки", "owner_categories")
            .button("🏆 Доска лидеров", "owner_leaderboard")
            .button("⚖️ Перейти в режим модерации (/a)", "owner_to_moderation")
            .button("⚙️ Настройки системы", "owner_settings")
            .adjust(1)
            .as_markup())

def get_catcon_main_kb() -> InlineKeyboardMarkup:
    """Главное меню управления кластерами (категориями)."""
    return (PremiumBuilder()
            .button(f"{EMOJI_BOX} УПРАВЛЕНИЕ КЛАСТЕРАМИ", CatConCD(action="list"))
            .primary("СОЗДАТЬ НОВЫЙ КЛАСТЕР", CatConCD(action="start"))
            .adjust(1)
            .back(NavCD(to="admin_menu"))
            .as_markup())

def get_catcon_options_kb(options: list[str], action: str) -> InlineKeyboardMarkup:
    """Выбор опций в конструкторе (Оператор, Тип)."""
    builder = PremiumBuilder()
    for opt in options:
        builder.button(opt, CatConCD(action=action, value=opt))
    builder.adjust(1)
    builder.cancel(CatConCD(action="cancel"))
    return builder.as_markup()

def get_catcon_confirm_kb() -> InlineKeyboardMarkup:
    """Подтверждение создания категории."""
    return (PremiumBuilder()
            .primary("ПОДТВЕРДИТЬ СОЗДАНИЕ", CatConCD(action="confirm"))
            .cancel(CatConCD(action="cancel"))
            .adjust(1)
            .as_markup())

def get_cat_manage_list_kb(categories: list) -> InlineKeyboardMarkup:
    """Список всех кластеров для редактирования."""
    builder = PremiumBuilder()
    for cat in categories:
        emoji = "🏮 " if getattr(cat, "is_priority", False) else ""
        status = "🟢" if cat.is_active else "🔴"
        title = f"{emoji}{status} {cat.title} | {cat.payout_rate} USDT"
        builder.button(title, CatManageCD(action="view", cat_id=cat.id))
    builder.adjust(1)
    builder.back(NavCD(to="admin_menu"))
    return builder.as_markup()

def get_cat_manage_detail_kb(cat: Any) -> InlineKeyboardMarkup:
    """Детальное управление конкретным кластером."""
    builder = PremiumBuilder()
    active_text = "🔴 ОТКЛЮЧИТЬ" if cat.is_active else "🟢 ВКЛЮЧИТЬ"
    builder.button(active_text, CatManageCD(action="toggle_active", cat_id=cat.id))
    
    priority_text = "🏮 УБРАТЬ ПРИОРИТЕТ" if getattr(cat, "is_priority", False) else "🏮 В ПРИОРИТЕТ"
    builder.button(priority_text, CatManageCD(action="toggle_priority", cat_id=cat.id))
    
    builder.button("💰 ИЗМЕНИТЬ СТАВКУ", CatManageCD(action="edit_price", cat_id=cat.id))
    builder.danger("УДАЛИТЬ КЛАСТЕР", CatManageCD(action="confirm_delete", cat_id=cat.id))
    
    builder.adjust(2, 1, 1)
    builder.back(CatConCD(action="list"), "К СПИСКУ")
    return builder.as_markup()

def get_cat_manage_confirm_delete_kb(cat_id: int) -> InlineKeyboardMarkup:
    """Подтверждение удаления кластера."""
    return (PremiumBuilder()
            .danger("⚠️ ДА, УДАЛИТЬ БЕЗВОЗВРАТНО", CatManageCD(action="delete", cat_id=cat_id))
            .cancel(CatManageCD(action="view", cat_id=cat_id))
            .adjust(1)
            .as_markup())

def get_admin_main_kb() -> InlineKeyboardMarkup:
    """Общий fallback для обратной совместимости (опционально)."""
    return get_moderator_main_kb()
