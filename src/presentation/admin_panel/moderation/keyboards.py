"""Silver Sakura — Клавиатуры модерации (Unified Edition)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.presentation.common.factory import AdminGradeCD, AdminQueueCD, AdminSearchCD, AdminSellerQueueCD, NavCD, QRDeliveryCD
from src.presentation.common.base import PremiumBuilder
from src.presentation.common.constants import *


def get_mod_dashboard_kb(stats: dict) -> InlineKeyboardMarkup:
    """Главный пульт управления модерацией."""
    builder = PremiumBuilder()

    # 1. ОСНОВНАЯ ОЧЕРЕДЬ (Большая кнопка)
    builder.primary(f"{EMOJI_BOX} СКЛАД (НОВЫЕ: {stats['warehouse']})", AdminSellerQueueCD(action="list", status="pending"))

    # 2. ВЫДАННЫЕ и БЛОКНУТЫЕ (Рядом)
    builder.button(f"📟 ВЫДАННЫЕ ({stats['issued']})", AdminSellerQueueCD(action="list", status="in_work"))
    builder.button("🚫 БЛОКНУТЫЕ (24H)", "mod_blocked_folder")

    # 3. ПРОВЕРКА (Большая)
    builder.primary(f"✨ ПРОВЕРКА ({stats['verification']})", AdminSellerQueueCD(action="list", status="verification"))

    # 4. ПОИСК И ПОДДЕРЖКА
    builder.button(f"{EMOJI_SEARCH} ПОИСК", "mod_search")
    from src.presentation.common.factory import AdminSupportCD
    builder.button("🛡 ТИКЕТЫ", AdminSupportCD(action="list"))

    builder.adjust(1, 2, 1, 2)
    builder.back(NavCD(to="menu"), "ВЕРНУТЬСЯ В МЕНЮ")
    return builder.as_markup()


def get_sellers_queue_kb(sellers: list, status: str) -> InlineKeyboardMarkup:
    """Список продавцов, у которых есть активы в выбранном статусе."""
    builder = PremiumBuilder()

    for s in sellers:
        name = s['username'] if s['username'] else f"ID:{s['user_id']}"
        # Формируем кнопку перехода к рабочему столу этого селлера
        builder.button(
            text=f"👤 {name} ({s['count']} шт.)", 
            callback_data=AdminSellerQueueCD(user_id=s['user_id'], action="view", status=status)
        )

    builder.adjust(1)
    builder.refresh(f"mod_q:refresh:{status}", "🔄 ОБНОВИТЬ")
    builder.back("mod_back_dash", "❮ НАЗАД")
    return builder.as_markup()


def get_seller_workspace_kb(
    items: list, 
    selected_ids: set[int], 
    user_id: int, 
    status: str, 
    page: int, 
    total: int,
    page_size: int = 10
) -> InlineKeyboardMarkup:
    """Универсальное рабочее пространство модератора: выбор + действия."""
    builder = PremiumBuilder()

    # 1. Список айтемов с мульти-выбором
    for item in items:
        is_sel = item.id in selected_ids
        icon = "✅" if is_sel else "⬜️"
        phone = item.phone_normalized
        if phone and len(phone) == 11:
            display = f"+{phone[0]} ({phone[1:4]}) {phone[4:7]}-{phone[7:9]}-{phone[9:]}"
        else:
            display = f"📦 АКТИВ #{item.id}"
            
        builder.button(
            text=f"{icon} {display}", 
            callback_data=AdminSellerQueueCD(user_id=user_id, action="toggle", status=status, page=page, val=str(item.id))
        )

    builder.adjust(1)

    # 2. Управление выделением
    sel_count = len(selected_ids)
    if sel_count > 0:
        builder.row(
            InlineKeyboardButton(text=f"✅ ЗАЧЁТ ({sel_count})", callback_data=AdminSellerQueueCD(user_id=user_id, action="apply", status=status, page=page, val="accept").pack()),
            InlineKeyboardButton(text=f"❌ БРАК ({sel_count})", callback_data=AdminSellerQueueCD(user_id=user_id, action="apply", status=status, page=page, val="reject").pack())
        )
        builder.row(
            InlineKeyboardButton(text=f"🚫 БЛОК ({sel_count})", callback_data=AdminSellerQueueCD(user_id=user_id, action="apply", status=status, page=page, val="block").pack()),
            InlineKeyboardButton(text="🧹 ОЧИСТИТЬ", callback_data=AdminSellerQueueCD(user_id=user_id, action="apply", status=status, page=page, val="clear").pack())
        )
    else:
        builder.row(
            InlineKeyboardButton(text="✔️ ВЫБРАТЬ ВСЕ", callback_data=AdminSellerQueueCD(user_id=user_id, action="apply", status=status, page=page, val="select_all").pack()),
            InlineKeyboardButton(text="🔎 ДЕТАЛЬНО", callback_data=AdminSellerQueueCD(user_id=user_id, action="apply", status=status, page=page, val="take_next").pack())
        )

    # 3. Пагинация
    max_page = (max(total, 1) - 1) // page_size
    if max_page > 0:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="⬅️", callback_data=AdminSellerQueueCD(user_id=user_id, action="view", status=status, page=page-1).pack()))
        nav.append(InlineKeyboardButton(text=f"{page+1}/{max_page+1}", callback_data="noop"))
        if page < max_page:
            nav.append(InlineKeyboardButton(text="➡️", callback_data=AdminSellerQueueCD(user_id=user_id, action="view", status=status, page=page+1).pack()))
        builder.row(*nav)

    # 4. Сервисные функции
    if status in ("in_work", "verification"):
        builder.row(InlineKeyboardButton(text="♻️ ВЕРНУТЬ НА СКЛАД", callback_data=AdminSellerQueueCD(user_id=user_id, action="return_warehouse", status=status).pack()))

    builder.back(AdminSellerQueueCD(action="list", status=status), "❮ К СПИСКУ ПРОДАВЦОВ")
    return builder.as_markup()


def get_qr_delivery_main_kb() -> InlineKeyboardMarkup:
    """Главное меню QR-доставки."""
    builder = PremiumBuilder()
    builder.primary("🚚 НАЧАТЬ ВЫДАЧУ", QRDeliveryCD(action="op_list"))
    builder.back(NavCD(to="menu"), "В ГЛАВНОЕ МЕНЮ")
    return builder.as_markup()


def get_qr_delivery_operators_kb(categories: list) -> InlineKeyboardMarkup:
    """Выбор оператора для доставки."""
    builder = PremiumBuilder()
    for cat in categories:
        builder.button(f"📶 {cat.title}", QRDeliveryCD(action="op_pick", val=str(cat.id)))
    builder.adjust(2)
    builder.back(QRDeliveryCD(action="menu"), "❮ НАЗАД")
    return builder.as_markup()


def get_mod_inspector_kb(item_id: int, remaining: int) -> InlineKeyboardMarkup:
    """Управление карточкой eSIM (ЗАЧЁТ / БРАК / БЛОК)."""
    builder = PremiumBuilder()
    builder.primary("ЗАЧЁТ", AdminGradeCD(item_id=item_id, action="accept"))
    builder.button("❌ БРАК", AdminGradeCD(item_id=item_id, action="reject"))
    builder.button("🚫 БЛОК", AdminGradeCD(item_id=item_id, action="block"))
    builder.button("📵 НЕ СКАН", AdminGradeCD(item_id=item_id, action="not_scan"))
    if remaining > 1:
        builder.button(f"⏭ ПРОПУСТИТЬ (ЕЩЁ {remaining - 1})", AdminQueueCD(action="next", item_id=item_id))
    builder.button("⏸ ПРИОСТАНОВИТЬ", "mod_pause")
    builder.adjust(1, 3, 1, 1)
    return builder.as_markup()


def get_mod_reasons_kb(item_id: int, type_key: str) -> InlineKeyboardMarkup:
    """Выбор причины отказа/блока."""
    builder = PremiumBuilder()
    reasons = {
        "reject": ["Плохое фото", "Не тот оператор", "Дубликат", "Истек срок"],
        "block": ["Фрод", "Черный список", "Жалоба", "Тест"],
        "not_scan": ["QR не читается", "Пустой файл", "Ошибка сети"],
    }
    for r in reasons.get(type_key, ["Другое"]):
        safe_r = r.replace(":", "|")
        builder.button(r, AdminGradeCD(item_id=item_id, action="reason", val=f"{type_key}|{safe_r}"))
    builder.adjust(1)
    builder.button("✍️ СВОЙ КОММЕНТАРИЙ", AdminGradeCD(item_id=item_id, action="reason", val=f"{type_key}|CUSTOM"))
    builder.back(AdminGradeCD(item_id=item_id, action="cancel_defect"), "« ОТМЕНА")
    return builder.as_markup()


def get_search_filters_kb(query: str, current_filter: str) -> InlineKeyboardMarkup:
    """Кнопки фильтрации результатов поиска."""
    builder = PremiumBuilder()
    
    filters = [
        ("all", "🔍 ВСЕ"),
        ("prio", "⭐ ПРИОРИТЕТ"),
        ("sla8", "🟡 SLA 8м"),
        ("sla15", "🔴 SLA 15м"),
    ]
    
    for f_type, label in filters:
        text = f"● {label}" if current_filter == f_type else label
        builder.button(text, AdminSearchCD(action="filter", filter_type=f_type, query=query))
        
    builder.adjust(2)
    builder.button("⚡ ЗАБРАТЬ ВСЕ НАЙДЕННЫЕ", AdminSearchCD(action="take_all", query=query, filter_type=current_filter))
    builder.back("mod_search", "❮ К ПОИСКУ")
    return builder.as_markup()


def get_search_results_kb(items: list) -> InlineKeyboardMarkup:
    """Список результатов поиска."""
    builder = PremiumBuilder()
    for item in items:
        phone = item.phone_normalized
        ident = f"...{phone[-4:]}" if phone else f"#{item.id}"
        builder.button(f"🔍 {item.category.title} | {ident}", AdminGradeCD(item_id=item.id, action="take"))
    
    builder.adjust(1)
    builder.back("mod_search", "❮ НАЗАД")
    return builder.as_markup()


def get_blocked_list_kb() -> InlineKeyboardMarkup:
    """Клавиатура раздела Блокнутые."""
    builder = PremiumBuilder()
    builder.refresh("mod_blocked_folder", "🔄 ОБНОВИТЬ СПИСОК")
    builder.back("mod_back_dash")
    return builder.as_markup()
