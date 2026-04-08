"""Silver Sakura — Клавиатуры модерации."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from src.keyboards.base import PremiumBuilder
from src.keyboards.constants import *
from src.callbacks.moderation import AdminQueueCD, AdminGradeCD, AdminBatchCD, AdminSellerQueueCD, AdminSearchCD
from src.keyboards.factory import NavCD

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
        
    builder.back(NavCD(to="admin_menu"))
    return builder.as_markup()

def get_mod_dashboard_kb(total_pending: int, my_in_work: int) -> InlineKeyboardMarkup:
    """Главный экран модератора."""
    builder = PremiumBuilder()
    
    if my_in_work > 0:
        builder.primary(f"🔥 ПРОДОЛЖИТЬ РАБОТУ ({my_in_work})", "mod_my_work_folder")
    
    builder.button(f"🚀 ОЧЕРЕДЬ АКТИВОВ ({total_pending})", "mod_queue_folder")
    builder.button(f"{EMOJI_SEARCH} ПОИСК ПО НОМЕРУ", "mod_search")
    builder.button(f"{EMOJI_BOX} BATCH-МАСТЕР", AdminBatchCD(action="start", val="0"))
    
    builder.adjust(1)
    builder.back(NavCD(to="admin_menu"), "ВЕРНУТЬСЯ В МЕНЮ")
    return builder.as_markup()

def get_my_work_folder_kb() -> InlineKeyboardMarkup:
    """Папка действий с личными активами."""
    return (PremiumBuilder()
            .primary("📑 КАРТОЧКИ (ПО ОДНОЙ)", AdminQueueCD(action="next"))
            .button("📦 BATCH-РЕЖИМ (МОИ)", AdminBatchCD(action="start", val="my"))
            .adjust(1)
            .back("mod_back_dash")
            .as_markup())

def get_queue_folder_kb() -> InlineKeyboardMarkup:
    """Папка действий с общей очередью."""
    return (PremiumBuilder()
            .primary("📑 КАРТОЧКИ (ПО ОДНОЙ)", AdminQueueCD(action="start"))
            .button("👥 ПО ПРОДАВЦАМ", AdminSellerQueueCD(action="list"))
            .button("📦 BATCH-РЕЖИМ (ОБЩАЯ)", AdminBatchCD(action="start", val="0"))
            .adjust(1)
            .back("mod_back_dash")
            .as_markup())

def get_sellers_queue_kb(sellers_data: list) -> InlineKeyboardMarkup:
    """Список продавцов с ожидающими активами."""
    builder = PremiumBuilder()
    for s in sellers_data:
        name = f"@{s['username']}" if s['username'] else f"ID:{s['user_id']}"
        text = f"👤 {name} | ⏳ {s['count']}"
        builder.button(text, AdminSellerQueueCD(user_id=str(s['user_id']), action="view"))
    
    builder.adjust(1)
    builder.refresh("mod_q:refresh", "ОБНОВИТЬ ОЧЕРЕДЬ")
    builder.back(NavCD(to="admin_menu"))
    return builder.as_markup()

def get_seller_detail_actions_kb(user_id: int, pending_count: int) -> InlineKeyboardMarkup:
    """Действия над активами конкретного продавца."""
    builder = PremiumBuilder()
    
    # Кнопки взятия в работу
    builder.primary(f"⚡️ ВЗЯТЬ ВСЁ ({pending_count})", AdminSellerQueueCD(user_id=str(user_id), action="take_all"))
    
    if pending_count > 5:
        builder.button("🔹 ВЗЯТЬ 5 ШТ", AdminSellerQueueCD(user_id=str(user_id), action="take_5"))
    if pending_count > 10:
        builder.button("🔹 ВЗЯТЬ 10 ШТ", AdminSellerQueueCD(user_id=str(user_id), action="take_10"))
        
    builder.adjust(1)
    builder.back(AdminQueueCD(action="start"), "К ОЧЕРЕДИ")
    return builder.as_markup()

def get_mod_inspector_kb(item_id: int, remaining: int) -> InlineKeyboardMarkup:
    """Управление карточкой eSIM (ЗАЧЁТ / БРАК / БЛОК)."""
    builder = PremiumBuilder()
    
    # Основные действия
    builder.primary("✅ ЗАЧЁТ", AdminGradeCD(item_id=item_id, action="accept"))
    
    builder.row(
        builder.button("❌ БРАК", AdminGradeCD(item_id=item_id, action="reject")).button,
        builder.button("🚫 БЛОК", AdminGradeCD(item_id=item_id, action="block")).button,
        builder.button("📵 НЕ СКАН", AdminGradeCD(item_id=item_id, action="not_scan")).button
    )
    
    if remaining > 0:
        builder.button(f"⏭ ПРОПУСТИТЬ (ЕЩЁ {remaining})", AdminQueueCD(action="next"))
    
    builder.adjust(1, 3, 1)
    builder.button("⏸ ПРИОСТАНОВИТЬ", "mod_pause")
    return builder.as_markup()

def get_undo_kb(item_id: int) -> InlineKeyboardMarkup:
    """Кнопка отмены последнего действия."""
    return (PremiumBuilder()
            .button("↩️ ОТМЕНИТЬ (UNDO)", AdminGradeCD(item_id=item_id, action="undo"))
            .adjust(1)
            .as_markup())

def get_mod_reasons_kb(item_id: int, type_key: str) -> InlineKeyboardMarkup:
    """Выбор причины отказа/блока."""
    builder = PremiumBuilder()
    
    reasons = {
        "reject": ["Плохое фото", "Не тот оператор", "Дубликат", "Истек срок"],
        "block": ["Фрод", "Черный список", "Жалоба", "Тест"],
        "not_scan": ["QR не читается", "Пустой файл", "Ошибка сети"]
    }
    
    for r in reasons.get(type_key, ["Другое"]):
        # Формируем колбэк вручную, так как он сложный (mod_rf:ID:TYPE:REASON)
        builder.button(r, f"mod_rf:{item_id}:{type_key}:{r}")
        
    builder.adjust(1)
    # Кнопка своего комментария
    builder.button("✍️ СВОЙ КОММЕНТАРИЙ", f"mod_rc:{item_id}:{type_key}")
    # Отмена
    builder.back(AdminGradeCD(item_id=item_id, action="cancel_defect"), "« ОТМЕНА")
    
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
    builder.button("✔️ ВЫБРАТЬ ВСЕ", AdminBatchCD(action="select_all"))
    builder.button("🗑 СБРОС", AdminBatchCD(action="clear"))
    builder.adjust(2)
    
    # Навигация
    builder.pagination("mod_batch_pg", page, total, 10)
    
    # Действие
    if selected_ids:
        builder.primary(f"⚡️ ПРИМЕНИТЬ ({len(selected_ids)})", AdminBatchCD(action="apply", val="0"))
        
    builder.back(NavCD(to="admin_menu"))
    return builder.as_markup()

def get_batch_status_kb() -> InlineKeyboardMarkup:
    """Выбор статуса для массовой обработки."""
    return (PremiumBuilder()
            .primary("✅ ЗАЧЁТ (МАССОВО)", AdminBatchCD(action="status", val="accepted"))
            .button("❌ БРАК", AdminBatchCD(action="status", val="reject"))
            .button("🚫 БЛОК", AdminBatchCD(action="status", val="block"))
            .button("📵 НЕ СКАН", AdminBatchCD(action="status", val="not_scan"))
            .adjust(1, 3)
            .back(AdminBatchCD(action="start"), "« К ВЫБОРУ")
            .as_markup())

def get_batch_reasons_kb(type_key: str) -> InlineKeyboardMarkup:
    """Выбор причины для массовой обработки."""
    builder = PremiumBuilder()
    reasons = {
        "reject": ["Плохое фото", "Не тот оператор", "Дубликат", "Истек срок"],
        "block": ["Фрод", "Черный список", "Жалоба", "Тест"],
        "not_scan": ["QR не читается", "Пустой файл", "Ошибка сети"]
    }
    
    for r in reasons.get(type_key, ["Другое"]):
        builder.button(r, AdminBatchCD(action="reason", val=f"{type_key}:{r}"))
        
    builder.adjust(1)
    builder.button("✍️ СВОЙ КОММЕНТАРИЙ", AdminBatchCD(action="custom", val=type_key))
    builder.back(AdminBatchCD(action="apply"), "« НАЗАД")
    return builder.as_markup()
