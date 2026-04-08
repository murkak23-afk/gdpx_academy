"""Silver Sakura — Клавиатуры модерации."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from src.keyboards.base import PremiumBuilder
from src.keyboards.constants import *
from src.callbacks.moderation import AdminQueueCD, AdminGradeCD, AdminBatchCD, AdminSellerQueueCD, AdminSearchCD

def get_search_filters_kb(query: str, current_filter: str) -> InlineKeyboardMarkup:
    """Кнопки фильтрации результатов поиска."""
    builder = PremiumBuilder()
    filters = [
        ("📦 ВСЕ", "all"),
        ("🏮 ПРИО", "prio"),
        ("⚡️ SLA8", "sla8"),
        ("⌛️ SLA15", "sla15")
    ]
    
    for label, key in filters:
        text = f"✨ {label}" if key == current_filter else label
        builder.button(text, AdminSearchCD(action="filter", filter_type=key, query=query))
        
    builder.adjust(2, 2)
    return builder.as_markup()

def get_search_results_kb(items: list, query: str, filter_type: str) -> InlineKeyboardMarkup:
    """Список найденных активов."""
    builder = PremiumBuilder()
    
    for item in items:
        # Показываем номер или ID
        ident = item.phone_normalized if hasattr(item, "phone_normalized") and item.phone_normalized else f"#{item.id}"
        builder.button(f"🔍 {ident}", AdminGradeCD(item_id=item.id, action="take"))
        
    builder.adjust(1)
    
    if items:
        builder.primary("ВЗЯТЬ ВСЕ НАЙДЕННЫЕ", AdminSearchCD(action="take_all", query=query, filter_type=filter_type))
        
    builder.back("admin_menu")
    return builder.as_markup()

def get_mod_dashboard_kb(total_pending: int, my_in_work: int) -> InlineKeyboardMarkup:
    """Главный экран модератора."""
    builder = PremiumBuilder()
    
    if my_in_work > 0:
        builder.primary(f"🔥 ПРОДОЛЖИТЬ РАБОТУ ({my_in_work})", "mod_my_work_folder")
    
    builder.button(f"🚀 ОЧЕРЕДЬ АКТИВОВ ({total_pending})", AdminQueueCD(action="start"))
    builder.button(f"{EMOJI_SEARCH} ПОИСК ПО НОМЕРУ", "mod_search")
    builder.button(f"{EMOJI_BOX} BATCH-МАСТЕР", AdminBatchCD(action="start", val="0"))
    
    builder.adjust(1)
    builder.back(NavCD(to="admin_menu"), "ВЕРНУТЬСЯ В МЕНЮ")
    return builder.as_markup()

def get_sellers_queue_kb(sellers_data: list) -> InlineKeyboardMarkup:
    """Список продавцов с ожидающими активами."""
    builder = PremiumBuilder()
    for s in sellers_data:
        name = f"@{s['username']}" if s['username'] else f"ID:{s['user_id']}"
        text = f"👤 {name} | ⏳ {s['count']}"
        builder.button(text, AdminSellerQueueCD(user_id=s['user_id'], action="view"))
    
    builder.adjust(1)
    builder.refresh("mod_q:refresh", "ОБНОВИТЬ ОЧЕРЕДЬ")
    builder.back(NavCD(to="admin_menu"))
    return builder.as_markup()

def get_seller_detail_actions_kb(user_id: int, pending_count: int) -> InlineKeyboardMarkup:
    """Действия над активами конкретного продавца."""
    builder = PremiumBuilder()
    
    # Кнопки взятия в работу
    builder.primary(f"⚡️ ВЗЯТЬ ВСЁ ({pending_count})", AdminSellerQueueCD(user_id=user_id, action="take_all"))
    
    if pending_count > 5:
        builder.button("🔹 ВЗЯТЬ 5 ШТ", AdminSellerQueueCD(user_id=user_id, action="take_5"))
    if pending_count > 10:
        builder.button("🔹 ВЗЯТЬ 10 ШТ", AdminSellerQueueCD(user_id=user_id, action="take_10"))
        
    builder.adjust(1)
    builder.back(AdminQueueCD(action="start"), "К ОЧЕРЕДИ")
    return builder.as_markup()

def get_mod_inspector_kb(item_id: int, remaining: int) -> InlineKeyboardMarkup:
    """Клавиатура инспектора для оценки одного актива."""
    builder = PremiumBuilder()
    builder.primary(f"✅ ЗАЧЁТ (Осталось: {remaining})", AdminGradeCD(item_id=item_id, action="accept"))
    
    builder.button(f"{EMOJI_BOX} НЕ СКАН", AdminGradeCD(item_id=item_id, action="not_scan"))
    builder.button(f"{EMOJI_REJECT} БРАК", AdminGradeCD(item_id=item_id, action="reject"))
    builder.button(f"🚫 БЛОК", AdminGradeCD(item_id=item_id, action="block"))
    
    builder.adjust(1, 3)
    builder.button("⏸ ПРИОСТАНОВИТЬ", "mod_pause")
    return builder.as_markup()

def get_mod_reasons_kb(item_id: int, defect_type: str) -> InlineKeyboardMarkup:
    """Выбор причины брака или блока."""
    builder = PremiumBuilder()
    
    reasons = {
        "reject": ["Плохое качество", "Не тот оператор", "Дубликат", "Истек срок"],
        "block": ["Фрод", "Черный список", "Жалоба"],
        "not_scan": ["Пустой QR", "Ошибка ссылки"]
    }
    
    list_reasons = reasons.get(defect_type, ["Другое"])
    for r in list_reasons:
        builder.button(r, f"mod_rf:{item_id}:{defect_type}:{r}")
        
    builder.adjust(1)
    builder.back(AdminGradeCD(item_id=item_id, action="cancel_defect"), "НАЗАД")
    return builder.as_markup()

def get_batch_list_kb(items: list, selected_ids: set[int], page: int, total: int) -> InlineKeyboardMarkup:
    """Список активов с возможностью массового выделения."""
    builder = PremiumBuilder()
    
    # Кнопки выбора
    for item in items:
        is_sel = item.id in selected_ids
        icon = "✅" if is_sel else "⬜️"
        ident = item.phone_normalized if hasattr(item, "phone_normalized") and item.phone_normalized else f"#{item.id}"
        builder.button(f"{icon} {ident}", AdminBatchCD(action="toggle", val=str(item.id)))
        
    builder.adjust(2)
    
    # Управление выделением
    builder.row(
        builder.builder.button(text="✔️ ВЫБРАТЬ ВСЕ", callback_data=AdminBatchCD(action="select_all").pack()).button,
        builder.builder.button(text="🗑 СБРОС", callback_data=AdminBatchCD(action="clear").pack()).button
    )
    
    # Навигация
    builder.pagination("mod_batch_pg", page, total, 10)
    
    # Действие
    if selected_ids:
        builder.primary(f"⚡️ ПРИМЕНИТЬ ({len(selected_ids)})", AdminBatchCD(action="apply"))
        
    builder.back("admin_menu")
    return builder.as_markup()

def get_batch_status_kb() -> InlineKeyboardMarkup:
    """Выбор статуса для массового действия."""
    return (PremiumBuilder()
            .primary("✅ ПРИНЯТЬ ВСЁ", AdminBatchCD(action="status", val="accepted"))
            .button("📦 НЕ СКАН (МАСС)", AdminBatchCD(action="status", val="not_scan"))
            .button("❌ БРАК (МАСС)", AdminBatchCD(action="status", val="reject"))
            .button("🚫 БЛОК (МАСС)", AdminBatchCD(action="status", val="block"))
            .adjust(1)
            .back(AdminBatchCD(action="start"), "НАЗАД")
            .as_markup())

def get_batch_reasons_kb(status_type: str) -> InlineKeyboardMarkup:
    """Выбор причины для массового брака/блока."""
    builder = PremiumBuilder()
    
    reasons = {
        "reject": ["Плохое качество", "Не тот оператор", "Дубликат", "Истек срок"],
        "block": ["Фрод", "Черный список", "Жалоба"],
        "not_scan": ["Пустой QR", "Ошибка ссылки"]
    }
    
    list_reasons = reasons.get(status_type, ["Другое"])
    for r in list_reasons:
        builder.button(r, AdminBatchCD(action="reason", val=r))
        
    builder.adjust(1)
    builder.back(AdminBatchCD(action="apply"), "НАЗАД")
    return builder.as_markup()
