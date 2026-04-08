"""Silver Sakura — Клавиатуры селлера (Premium UX)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from src.keyboards.base import PremiumBuilder
from src.keyboards.constants import *
from src.keyboards.factory import (
    SellerMenuCD, NavCD, SellerAssetCD, SellerItemCD, 
    SellerSubmissionCD, SellerStatsCD, SellerSettingsCD,
    PinPadCD, SellerNotifCD
)

def get_seller_main_kb(has_accepted_codex: bool = True) -> InlineKeyboardMarkup:
    """Главное меню селлера в стиле Silver Sakura."""
    builder = PremiumBuilder()
    
    if not has_accepted_codex:
        # Если кодекс не принят, показываем только кнопку Кодекса и Поддержку
        builder.primary("🏯 ПРИНЯТЬ КОДЕКС АГЕНТА", "academy:start")
        builder.button("🛡 ПОДДЕРЖКА", SellerMenuCD(action="support"))
        builder.adjust(1)
    else:
        # Полноценное меню
        builder.primary("🧧 ЗАГРУЗИТЬ eSIM", SellerMenuCD(action="sell"))
        builder.row()
        builder.button("📊 МОИ АКТИВЫ", SellerMenuCD(action="assets"))
        builder.button("👤 МОЙ ПРОФИЛЬ", SellerMenuCD(action="profile"))
        builder.row()
        builder.button("💎 ВЫПЛАТЫ", SellerMenuCD(action="payouts"))
        builder.button("📈 СТАТИСТИКА", SellerMenuCD(action="stats"))
        builder.row()
        builder.button("📜 БАЗА ЗНАНИЙ", SellerMenuCD(action="info"))
        builder.button("🛡 ПОДДЕРЖКА", SellerMenuCD(action="support"))
        builder.adjust(1, 2, 2, 2)
        
    return builder.as_markup()

def get_seller_profile_kb() -> InlineKeyboardMarkup:
    """Клавиатура главного экрана Профиля."""
    return (PremiumBuilder()
            .button("📈 СТАТИСТИКА", SellerMenuCD(action="stats"))
            .button("⚙️ НАСТРОЙКИ", SellerMenuCD(action="settings"))
            .row()
            .button("📊 МОИ АКТИВЫ", SellerMenuCD(action="assets"))
            .back(NavCD(to="menu"), "В ГЛАВНОЕ МЕНЮ")
            .adjust(2, 1, 1)
            .as_markup())

def get_seller_stats_kb(current_period: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора периода статистики."""
    builder = PremiumBuilder()
    periods = [
        ("СЕГОДНЯ", "day"),
        ("НЕДЕЛЯ", "week"),
        ("МЕСЯЦ", "month"),
        ("ВСЁ ВРЕМЯ", "all")
    ]
    for label, key in periods:
        text = f"✨ {label}" if key == current_period else label
        builder.button(text, SellerStatsCD(period=key))
    
    builder.adjust(2, 2)
    builder.back(SellerMenuCD(action="profile"), "В ПРОФИЛЬ")
    return builder.as_markup()

def get_seller_settings_kb() -> InlineKeyboardMarkup:
    """Меню настроек профиля."""
    return (PremiumBuilder()
            .button("🛡 БЕЗОПАСНОСТЬ (PIN)", SellerSettingsCD(action="pin"))
            .button("👤 ЛИЧНЫЕ ДАННЫЕ", SellerSettingsCD(action="alias"))
            .row()
            .button("🎭 РЕЖИМ INCOGNITO", SellerSettingsCD(action="incognito"))
            .button("🔔 УВЕДОМЛЕНИЯ", SellerSettingsCD(action="notif"))
            .row()
            .button("🌐 ЯЗЫК / LANGUAGE", SellerSettingsCD(action="lang"))
            .button("📊 ЭКСПОРТ ДАННЫХ", SellerSettingsCD(action="export"))
            .adjust(2, 2, 2)
            .back(SellerMenuCD(action="profile"), "В ПРОФИЛЬ")
            .as_markup())

def get_pin_pad_kb(current_input: str, context: str) -> InlineKeyboardMarkup:
    """Цифровая клавиатура для ввода PIN."""
    builder = PremiumBuilder()
    for i in range(1, 10):
        builder.button(str(i), PinPadCD(action="digit", value=str(i), context=context))
    builder.button("⌫", PinPadCD(action="backspace", context=context))
    builder.button("0", PinPadCD(action="digit", value="0", context=context))
    if len(current_input) >= 4:
        builder.button("✅ OK", PinPadCD(action="confirm", context=context))
    else:
        builder.button("❌", PinPadCD(action="cancel", context=context))
    builder.adjust(3, 3, 3, 3)
    return builder.as_markup()

def get_notification_settings_kb(current_pref: str) -> InlineKeyboardMarkup:
    """Выбор режима уведомлений с индикацией текущего выбора."""
    builder = PremiumBuilder()
    
    options = [
        ("О каждой проверке", "full"),
        ("Итог за день", "summary"),
        ("Выключить", "none")
    ]
    
    for label, pref in options:
        text = f"✅ {label}" if pref == current_pref else f"▫️ {label}"
        builder.button(text, SellerNotifCD(preference=pref))
        
    builder.adjust(1)
    builder.back(SellerSettingsCD(action="main"), "В НАСТРОЙКИ")
    return builder.as_markup()

def get_language_settings_kb() -> InlineKeyboardMarkup:
    """Выбор языка интерфейса."""
    builder = PremiumBuilder()
    # Пока поддерживается только RU
    builder.button("✅ РУССКИЙ (RU)", SellerSettingsCD(action="lang_set", value="ru"))
    builder.adjust(1)
    builder.back(SellerSettingsCD(action="main"), "В НАСТРОЙКИ")
    return builder.as_markup()

def get_favorite_categories_kb(categories: list, favorite_ids: list[int]) -> InlineKeyboardMarkup:
    """Управление избранными категориями."""
    builder = PremiumBuilder()
    for cat in categories:
        is_fav = cat.id in favorite_ids
        icon = "⭐" if is_fav else "▫️"
        builder.button(f"{icon} {cat.title}", SellerSettingsCD(action="prefs", value=str(cat.id)))
    
    builder.adjust(1)
    builder.back(SellerSettingsCD(action="main"), "В НАСТРОЙКИ")
    return builder.as_markup()

def get_back_to_main_kb() -> InlineKeyboardMarkup:
    """Универсальная кнопка возврата в серебряном стиле."""
    return (PremiumBuilder()
            .button(f"{EMOJI_BACK} В главное меню", NavCD(to="menu"))
            .as_markup())

def get_categories_kb(categories: list, favorite_ids: list[int] = None, cancel_to: str = "menu") -> InlineKeyboardMarkup:
    """Выбор категории для загрузки активов (с избранными наверху)."""
    builder = PremiumBuilder()
    fav_ids = favorite_ids or []
    sorted_cats = sorted(
        categories, 
        key=lambda c: (c.id not in fav_ids, not getattr(c, "is_priority", False), c.title)
    )
    for cat in sorted_cats:
        is_fav = cat.id in fav_ids
        fav_icon = "⭐ " if is_fav else ""
        prio_icon = "🏮 " if getattr(cat, "is_priority", False) else "📦 "
        title = f"{fav_icon}{prio_icon}{cat.title} | {cat.payout_rate} USDT"
        builder.button(title, SellerAssetCD(category_id=cat.id))
    builder.adjust(1)
    builder.cancel(NavCD(to=cancel_to))
    return builder.as_markup()

def get_seller_assets_folders_kb(folders: list[dict], best_cat_id: int | None) -> InlineKeyboardMarkup:
    """Список кластеров с активами селлера."""
    builder = PremiumBuilder()
    sorted_folders = sorted(folders, key=lambda f: (f['category_id'] != best_cat_id, -f['total']))
    for f in sorted_folders:
        is_best = f['category_id'] == best_cat_id
        icon = "🏆" if is_best else "🗂"
        suffix = " 🔥" if is_best else ""
        btn_text = f"{icon} {f['title']}{suffix} [{f['total']}]"
        builder.button(btn_text, SellerAssetCD(category_id=f['category_id']))
    builder.adjust(1)
    builder.back(NavCD(to="menu"), "В ГЛАВНОЕ МЕНЮ")
    return builder.as_markup()

def get_seller_assets_items_kb(items: list, category_id: int, current_page: int, total_items: int, current_filter: str) -> InlineKeyboardMarkup:
    """Список конкретных активов внутри кластера с пагинацией и фильтрами."""
    builder = PremiumBuilder()
    filters = [
        ("📦 ВСЕ", "all"), 
        ("⏳ ОЖИДАЕТ", "pending"), 
        ("✅ ЗАЧТЕНО", "accepted"), 
        ("❌ БРАК", "rejected")
    ]
    for label, key in filters:
        text = f"✨ {label}" if key == current_filter else label
        builder.button(text, SellerAssetCD(category_id=category_id, page=0, filter_key=key))
    builder.adjust(2, 2)
    for item in items:
        status_val = item.status.value
        status_emoji = STATUS_EMOJI.get(status_val, "▫️")
        price = getattr(item, "fixed_payout_rate", "0.0")
        phone = getattr(item, "phone_normalized", None)
        ident = f"...{phone[-4:]}" if phone and len(phone) >= 4 else f"#{item.id}"
        text = f"{status_emoji} {ident} | {price} USDT"
        builder.button(text, SellerItemCD(item_id=item.id, action="view"))
    builder.adjust(2, 2, 1)
    builder.pagination("sel_asset_pg", current_page, total_items, 7, query=f"{category_id}:{current_filter}")
    builder.back(SellerMenuCD(action="assets"), "К КЛАСТЕРАМ")
    return builder.as_markup()

def get_seller_item_view_kb(item_id: int, category_id: int) -> InlineKeyboardMarkup:
    """Детальный просмотр актива."""
    return (PremiumBuilder()
            .danger("ОТОЗВАТЬ АКТИВ", SellerItemCD(item_id=item_id, action="delete"))
            .back(SellerAssetCD(category_id=category_id), "К СПИСКУ")
            .adjust(1)
            .as_markup())

def get_seller_payout_history_kb(current_period: str) -> InlineKeyboardMarkup:
    """Клавиатура истории выплат с фильтрами."""
    builder = PremiumBuilder()
    periods = [
        ("7 ДНЕЙ", "7"),
        ("30 ДНЕЙ", "30"),
        ("90 ДНЕЙ", "90"),
        ("ВСЁ ВРЕМЯ", "all")
    ]
    for label, key in periods:
        text = f"✨ {label}" if key == current_period else label
        builder.button(text, SellerStatsCD(period=key)) # Используем SellerStatsCD для периодов
    
    builder.adjust(2, 2)
    builder.button("📥 СКАЧАТЬ CSV", "payout_export_csv")
    builder.back(NavCD(to="menu"), "В ГЛАВНОЕ МЕНЮ")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()

def get_upload_finish_kb() -> InlineKeyboardMarkup:
    """Финальное подтверждение загрузки."""
    return (PremiumBuilder()
            .primary("ПОДТВЕРДИТЬ ИНТЕГРАЦИЮ", "upload_finish")
            .cancel("upload_cancel", "ОТМЕНИТЬ ВСЁ")
            .adjust(1)
            .as_markup())
