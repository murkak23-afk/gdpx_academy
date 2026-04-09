"""Silver Sakura — Клавиатуры владельца (Owner/Admin)."""

from __future__ import annotations

from typing import Any

from aiogram.types import InlineKeyboardMarkup

from src.keyboards.base import PremiumBuilder
from src.keyboards.constants import *
from src.keyboards.factory import CatConCD, CatManageCD, NavCD, OwnerUserCD
from src.callbacks.finance import FinancePayCD


def get_owner_main_kb() -> InlineKeyboardMarkup:
    """Главное меню Владельца (Полный контроль)."""
    return (PremiumBuilder()
            .button("🏯 КОМАНДНЫЙ ЦЕНТР", "owner_cmd_center")
            .button("💎 ВЫПЛАТЫ И ФИНАНСЫ", "owner_finance")
            .button("📈 АНАЛИТИКА И СТАТИСТИКА", "owner_stats")
            .button("🏷️ КАТЕГОРИИ И СТАВКИ", "owner_categories")
            .button("🏆 ДОСКА ЛИДЕРОВ", "owner_leaderboard")
            .button("👥 ПОЛЬЗОВАТЕЛИ И МОДЫ", "owner_users")
            .button("⚙️ НАСТРОЙКИ СИСТЕМЫ", "owner_settings")
            .button("🚨 МОНИТОРИНГ И АЛЕРТЫ", "owner_monitoring")
            .adjust(1)
            .primary("⚖️ РЕЖИМ МОДЕРАЦИИ (/a)", "owner_to_moderation")
            .as_markup())


def get_owner_finance_kb() -> InlineKeyboardMarkup:
    """Клавиатура раздела «Выплаты и финансы» (Владелец)."""
    return (PremiumBuilder()
            .button("💸 ПРОВЕСТИ ВЫПЛАТУ", FinancePayCD(action="list"))
            .button("📦 МАССОВЫЕ ВЫПЛАТЫ", "owner_finance_bulk")
            .button("📜 ИСТОРИЯ ВЫПЛАТ", FinancePayCD(action="history"))
            .button("➕ ПОПОЛНИТЬ БАЛАНС", "owner_finance_topup")
            .button("📊 СТАТИСТИКА ВЫПЛАТ", FinancePayCD(action="stats"))
            .button("🛡️ ФИНАНСОВЫЙ АУДИТ", "owner_finance_audit")
            .adjust(1)
            .back("owner_back_main")
            .as_markup())


def get_owner_users_kb() -> InlineKeyboardMarkup:
    """Главное меню раздела «Пользователи и моды»."""
    return (PremiumBuilder()
            .button("👥 ВСЕ ПОЛЬЗОВАТЕЛИ", OwnerUserCD(action="list", role="all"))
            .button("💰 ТОЛЬКО СЕЛЛЕРЫ", OwnerUserCD(action="list", role="seller"))
            .button("⚖️ ТОЛЬКО МОДЕРАТОРЫ", OwnerUserCD(action="list", role="admin"))
            .button("🔍 ПОИСК ПО ID", "owner_users_search")
            .button("➕ НАЗНАЧИТЬ РОЛЬ", "owner_settings_roles")
            .adjust(1)
            .back("owner_back_main")
            .as_markup())


def get_users_list_kb(users: list, page: int, total: int, role: str, page_size: int = 20) -> InlineKeyboardMarkup:
    """Список пользователей с пагинацией."""
    builder = PremiumBuilder()
    
    for u in users:
        icon = "⚖️" if u.role.value == "admin" else "👤"
        status = "🔴" if u.is_restricted else "🟢"
        name = f"@{u.username}" if u.username else f"ID: {u.telegram_id}"
        builder.button(f"{status} {icon} {name}", OwnerUserCD(action="view", user_id=u.id, page=page, role=role))
    
    builder.adjust(1)
    builder.pagination("ow_user_pg", page, total, page_size, query=role)
    builder.back(OwnerUserCD(action="main"), "« К ВЫБОРУ")
    return builder.as_markup()


def get_user_card_kb(user_id: int, current_role: str, is_restricted: bool, page: int, role_filter: str) -> InlineKeyboardMarkup:
    """Действия в карточке пользователя."""
    builder = PremiumBuilder()
    
    next_role_text = "🔨 СДЕЛАТЬ АДМИНОМ" if current_role == "seller" else "👤 СДЕЛАТЬ СЕЛЛЕРОМ"
    builder.button(next_role_text, OwnerUserCD(action="role", user_id=user_id, page=page, role=role_filter))
    
    status_text = "🔓 РАЗБЛОКИРОВАТЬ" if is_restricted else "🚫 ЗАБЛОКИРОВАТЬ"
    builder.button(status_text, OwnerUserCD(action="status", user_id=user_id, page=page, role=role_filter))
    
    builder.button("💰 СБРОСИТЬ БАЛАНС", OwnerUserCD(action="balance", user_id=user_id, page=page, role=role_filter))
    builder.button("📜 ИСТОРИЯ ДЕЙСТВИЙ", OwnerUserCD(action="history", user_id=user_id, page=page, role=role_filter))
    
    builder.adjust(1)
    builder.back(OwnerUserCD(action="list", page=page, role=role_filter), "« К СПИСКУ")
    return builder.as_markup()


def get_owner_monitoring_kb() -> InlineKeyboardMarkup:
    """Клавиатура раздела «Мониторинг и алерты»."""
    return (PremiumBuilder()
            .button("🔄 ОБНОВИТЬ ДАННЫЕ", "owner_monitoring")
            .button("🛑 ПРИОСТАНОВИТЬ МОДОВ", "owner_mods_suspend")
            .button("▶️ ВОЗОБНОВИТЬ МОДОВ", "owner_mods_resume")
            .button("🛠️ РЕЖИМ ОБСЛУЖИВАНИЯ", "owner_settings_maintenance")
            .adjust(1, 2, 1)
            .back("owner_back_main")
            .as_markup())


def get_owner_settings_kb(maintenance_mode: bool) -> InlineKeyboardMarkup:
    """Клавиатура раздела «Настройки системы»."""
    m_text = "🔧 ВЫКЛ. ОБСЛУЖИВАНИЕ" if maintenance_mode else "🛠️ ВКЛ. ОБСЛУЖИВАНИЕ"
    return (PremiumBuilder()
            .button("🌐 ГЛОБАЛЬНЫЕ ПАРАМЕТРЫ", "owner_settings_global")
            .button("🔑 РОЛИ И ПРАВА", "owner_settings_roles")
            .button("🔔 РАССЫЛКИ", "owner_settings_notify")
            .button("🔐 БЕЗОПАСНОСТЬ И ЛОГИ", "owner_settings_security")
            .button("💾 BACKUP / ЭКСПОРТ", "owner_settings_backup")
            .button(m_text, "owner_settings_maintenance")
            .adjust(1)
            .back("owner_back_main")
            .as_markup())


def get_owner_security_kb() -> InlineKeyboardMarkup:
    """Клавиатура раздела «Безопасность и логи»."""
    return (PremiumBuilder()
            .button("📜 АУДИТ ДЕЙСТВИЙ", "owner_sec_audit")
            .button("🔍 ПОИСК ПО НОМЕРУ", "owner_sec_audit_search")
            .button("🔑 ЛОГИ ВХОДОВ", "owner_sec_logins")
            .button("📊 УРОВЕНЬ ЛОГИРОВАНИЯ", "owner_sec_level")
            .button("🧹 ОЧИСТКА ЛОГОВ", "owner_sec_cleanup")
            .button("📤 ЭКСПОРТ ЛОГОВ", "owner_sec_export")
            .button("🛡️ КРИТ. УВЕДОМЛЕНИЯ", "owner_sec_alerts")
            .button("📍 АКТИВНЫЕ СЕССИИ", "owner_sec_sessions")
            .adjust(1)
            .back("owner_settings")
            .as_markup())


def get_owner_categories_kb(categories: list) -> InlineKeyboardMarkup:
    """Список всех категорий для Владельца."""
    builder = PremiumBuilder()
    for cat in categories:
        emoji = "🏮 " if cat.is_priority else ""
        status = "🟢" if cat.is_active else "🔴"
        title = f"{emoji}{status} {cat.title} | {cat.payout_rate} USDT"
        builder.button(title, CatManageCD(action="view", cat_id=cat.id))
    
    builder.adjust(1)
    builder.primary("➕ СОЗДАТЬ КАТЕГОРИЮ", CatConCD(action="start"))
    builder.button("💹 МАССОВАЯ СМЕНА СТАВОК", "owner_cat_mass_edit")
    builder.button("📜 ИСТОРИЯ ИЗМЕНЕНИЙ", "owner_cat_history")
    builder.adjust(1)
    builder.back("owner_back_main")
    return builder.as_markup()


def get_owner_category_detail_kb(cat_id: int, is_active: bool, is_priority: bool) -> InlineKeyboardMarkup:
    """Детальное управление конкретной категорией."""
    builder = PremiumBuilder()
    
    active_text = "🔴 ОТКЛЮЧИТЬ" if is_active else "🟢 ВКЛЮЧИТЬ"
    builder.button(active_text, CatManageCD(action="toggle_active", cat_id=cat_id))
    
    priority_text = "🏮 УБРАТЬ ПРИОРИТЕТ" if is_priority else "🏮 В ПРИОРИТЕТ"
    builder.button(priority_text, CatManageCD(action="toggle_priority", cat_id=cat_id))
    
    builder.button("💰 ИЗМЕНИТЬ СТАВКУ", CatManageCD(action="edit_price", cat_id=cat_id))
    builder.danger("🗑 УДАЛИТЬ КАТЕГОРИЮ", CatManageCD(action="confirm_delete", cat_id=cat_id))
    
    builder.adjust(2, 1, 1)
    builder.back("owner_categories", "« К СПИСКУ")
    return builder.as_markup()


def get_catcon_main_kb() -> InlineKeyboardMarkup:
    """Главное меню управления кластерами (категориями)."""
    return (
        PremiumBuilder()
        .button(f"{EMOJI_BOX} УПРАВЛЕНИЕ КЛАСТЕРАМИ", CatConCD(action="list"))
        .primary("СОЗДАТЬ НОВЫЙ КЛАСТЕР", CatConCD(action="start"))
        .button("💹 МАССОВАЯ СМЕНА СТАВОК", "owner_cat_mass_edit")
        .button("📜 ИСТОРИЯ ИЗМЕНЕНИЙ", "owner_cat_history")
        .adjust(1)
        .back("owner_back_main")
        .as_markup()
    )


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
    return (
        PremiumBuilder()
        .primary("ПОДТВЕРДИТЬ СОЗДАНИЕ", CatConCD(action="confirm"))
        .cancel(CatConCD(action="cancel"))
        .adjust(1)
        .as_markup()
    )


def get_cat_manage_list_kb(categories: list) -> InlineKeyboardMarkup:
    """Список всех кластеров для редактирования."""
    builder = PremiumBuilder()
    for cat in categories:
        emoji = "🏮 " if getattr(cat, "is_priority", False) else ""
        status = "🟢" if cat.is_active else "🔴"
        # Будем передавать количество eSIM в тексте кнопки снаружи или считать здесь, если данные переданы
        title = f"{emoji}{status} {cat.title} | {cat.payout_rate} USDT"
        builder.button(title, CatManageCD(action="view", cat_id=cat.id))
    builder.adjust(1)
    builder.back(CatConCD(action="list"), "« НАЗАД")
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
    return (
        PremiumBuilder()
        .danger("⚠️ ДА, УДАЛИТЬ БЕЗВОЗВРАТНО", CatManageCD(action="delete", cat_id=cat_id))
        .cancel(CatManageCD(action="view", cat_id=cat_id))
        .adjust(1)
        .as_markup()
    )
