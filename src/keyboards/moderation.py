from __future__ import annotations
from datetime import datetime, timezone

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from src.callbacks.moderation import AdminQueueCD, AdminGradeCD, AdminBatchCD, AdminSellerQueueCD, AdminSearchCD
from src.keyboards.factory import NavCD

def get_mod_dashboard_kb(total_pending: int, my_in_work: int) -> InlineKeyboardMarkup:
    """Главный дашборд с папками."""
    builder = InlineKeyboardBuilder()

    if my_in_work > 0:
        builder.button(text=f"📂 ВАШИ АКТИВЫ ({my_in_work})", callback_data="mod_my_work_folder")

    # Папка "Очередь" (активна всегда, даже если там 0, чтобы можно было проверить)
    builder.button(text=f"📂 ОБЩАЯ ОЧЕРЕДЬ ({total_pending})", callback_data="mod_queue_folder")
    
    builder.button(text="🔍 ИНТЕЛЛЕКТУАЛЬНЫЙ ПОИСК", callback_data="mod_search")

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="❮ ВЕРНУТЬСЯ В МЕНЮ", callback_data=NavCD(to="admin_menu").pack()))
    return builder.as_markup()

def get_my_work_folder_kb() -> InlineKeyboardMarkup:
    """Подменю: действия с активами в работе."""
    builder = InlineKeyboardBuilder()
    
    builder.button(text=f"🔥 ИНСПЕКТОР (ПО 1 ШТ)", callback_data="mod_continue_work")
    builder.button(text=f"📦 МАСС-ДЕЙСТВИЯ", callback_data="mod_batch_my")
    
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="❮ НАЗАД В ДАШБОРД", callback_data="mod_back_dash"))
    return builder.as_markup()

def get_queue_folder_kb() -> InlineKeyboardMarkup:
    """Подменю: действия с общей очередью."""
    builder = InlineKeyboardBuilder()
    
    builder.button(text=f"🚀 ПРОСМОТР ОЧЕРЕДИ", callback_data=AdminQueueCD(action="start").pack())
    builder.button(text="📦 МАСС-ДЕЙСТВИЯ", callback_data=AdminBatchCD(action="start").pack())
    
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="❮ НАЗАД В ДАШБОРД", callback_data="mod_back_dash"))
    return builder.as_markup()



def get_inspector_stub_kb(item_id: int) -> InlineKeyboardMarkup:
    """Заглушка панели инспектора (будет расширена в Этапе 3)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ ПРИНЯТЬ", callback_data=AdminGradeCD(item_id=item_id, action="accept"))
    builder.button(text="❌ БРАК / БЛОК", callback_data=AdminGradeCD(item_id=item_id, action="reject"))
    builder.adjust(2)
    return builder.as_markup()

def get_queue_actions_kb(has_priority: bool) -> InlineKeyboardMarkup:
    """Клавиатура выбора объема работы."""
    builder = InlineKeyboardBuilder()

    if has_priority:
        builder.button(text="🏮 ВЗЯТЬ ВСЕ ПРИОРИТЕТНЫЕ", callback_data="mod_take:priority")

    builder.button(text="🔋 Взять 5 штук", callback_data="mod_take:5")
    builder.button(text="🔋 Взять 10 штук", callback_data="mod_take:10")
    builder.button(text="🔋 Взять 20 штук", callback_data="mod_take:20")

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔄 ОБНОВИТЬ", callback_data="mod_q:refresh"))
    builder.row(InlineKeyboardButton(text="❮ НАЗАД", callback_data="mod_back_dash"))
    return builder.as_markup()

def get_sellers_queue_kb(sellers_data: list) -> InlineKeyboardMarkup:
    """Список кнопок продавцов с индикацией SLA."""
    builder = InlineKeyboardBuilder()

    for data in sellers_data:
        user = data['user']
        count = data['count']
        oldest = data['oldest']

        # Расчет SLA
        wait_min = int((datetime.now(timezone.utc) - oldest).total_seconds() / 60)
        sla_emoji = "🔴" if wait_min > 15 else "🟡" if wait_min > 8 else "🟢"

        name = f"@{user.username}" if user.username else f"ID:{user.id}"
        btn_text = f"{sla_emoji} {name} | {count} шт. ({wait_min}м)"

        builder.button(text=btn_text, callback_data=AdminSellerQueueCD(user_id=user.id, action="view"))

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔄 ОБНОВИТЬ", callback_data="mod_q:refresh"))
    builder.row(InlineKeyboardButton(text="❮ НАЗАД", callback_data="mod_back_dash"))
    return builder.as_markup()

def get_seller_detail_actions_kb(user_id: int, total_count: int) -> InlineKeyboardMarkup:
    """Кнопки захвата активов конкретного продавца."""
    builder = InlineKeyboardBuilder()

    builder.button(text=f"🚀 ВЗЯТЬ ВСЁ ({total_count} шт)", callback_data=AdminSellerQueueCD(user_id=user_id, action="take_all"))

    # Кнопки порционного взятия
    for n in [5, 10, 20]:
        if total_count > n:
            builder.button(text=f"🔋 Взять {n} шт", callback_data=AdminSellerQueueCD(user_id=user_id, action=f"take_{n}"))

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="❮ К ОЧЕРЕДИ", callback_data="mod_q:refresh"))
    return builder.as_markup()

def get_mod_inspector_kb(item_id: int, remaining: int) -> InlineKeyboardMarkup:
    """Главный пульт инспектора."""
    builder = InlineKeyboardBuilder()

    builder.button(text=f"✅ ЗАЧЁТ (Осталось: {remaining})", callback_data=AdminGradeCD(item_id=item_id, action="accept"))

    builder.button(text="📦 НЕ СКАН", callback_data=AdminGradeCD(item_id=item_id, action="not_scan"))
    builder.button(text="❌ БРАК", callback_data=AdminGradeCD(item_id=item_id, action="reject"))
    builder.button(text="🚫 БЛОК", callback_data=AdminGradeCD(item_id=item_id, action="block"))

    builder.adjust(1, 3)
    builder.row(InlineKeyboardButton(text="⏸ ПРИОСТАНОВИТЬ", callback_data="mod_pause"))
    return builder.as_markup()

def get_mod_reasons_kb(item_id: int, mode: str) -> InlineKeyboardMarkup:
    """Папка готовых причин отказа."""
    builder = InlineKeyboardBuilder()

    reasons = {
        "not_scan": ["Плохое фото", "Не QR-код", "Обрезано"],
        "reject": ["Не тот оператор", "Уже активен", "Ошибка данных"],
        "block": ["ФРОД / ДУБЛИКАТ", "Тестовый прогон", "Нарушение правил"]
    }

    for r in reasons.get(mode, ["Другое"]):
        builder.button(text=r, callback_data=f"mod_rf:{item_id}:{mode}:{r[:20]}")

    builder.button(text="✍️ СВОЙ КОММЕНТАРИЙ", callback_data=f"mod_rc:{item_id}:{mode}")
    builder.adjust(1)
    
    # ИСПРАВЛЕНИЕ: action="cancel_defect" вместо "take"
    builder.row(InlineKeyboardButton(
        text="❮ НАЗАД К СИМКЕ",
        callback_data=AdminGradeCD(item_id=item_id, action="cancel_defect").pack()
    ))
    return builder.as_markup()

def get_search_filters_kb(query: str, current_filter: str) -> InlineKeyboardMarkup:
    """Верхняя панель: Переключение фильтров SLA."""
    builder = InlineKeyboardBuilder()

    filters = [
        ("📦 Все", "all"),
        ("🏮 Приоритет", "prio"),
        ("🟡 >8 мин", "sla8"),
        ("🔴 >15 мин", "sla15")
    ]

    for label, key in filters:
        text = f"▪️ {label}" if key == current_filter else label
        builder.button(text=text, callback_data=AdminSearchCD(action="filter", filter_type=key, query=query[:15]).pack())

    builder.adjust(2, 2)
    return builder.as_markup()


def get_search_results_kb(items: list, query: str, filter_type: str) -> InlineKeyboardMarkup:
    """Вывод результатов поиска."""
    builder = InlineKeyboardBuilder()

    for item in items:
        wait_min = int((datetime.now(timezone.utc) - item.created_at).total_seconds() / 60)
        sla = "🔴" if wait_min > 15 else "🟡" if wait_min > 8 else "🟢"
        phone = getattr(item, "phone_normalized", None)
        ident = f"...{phone[-4:]}" if phone and len(phone) >= 4 else f"#{item.id}"
        prio = "🏮 " if getattr(item.category, "is_priority", False) else ""

        btn_text = f"{sla} {prio}{ident} | {getattr(item, 'fixed_payout_rate', '0.0')} USDT"
        builder.button(text=btn_text, callback_data=AdminGradeCD(item_id=item.id, action="take").pack())

    builder.adjust(1)

    if items:
        builder.row(InlineKeyboardButton(
            text=f"🚀 ВЗЯТЬ ВСЕ НАЙДЕННЫЕ ({len(items)})",
            callback_data=AdminSearchCD(action="take_all", filter_type=filter_type, query=query[:15]).pack()
        ))

    builder.row(InlineKeyboardButton(text="🔍 НОВЫЙ ПОИСК", callback_data="mod_search"))
    builder.row(InlineKeyboardButton(text="❮ В ДАШБОРД", callback_data="mod_back_dash"))

    return builder.as_markup()

def get_batch_list_kb(items: list, selected_ids: set, page: int, total: int) -> InlineKeyboardMarkup:
    """Генерирует список активов с чекбоксами."""
    builder = InlineKeyboardBuilder()

    for item in items:
        mark = "☑️" if item.id in selected_ids else "◻️"
        phone = getattr(item, "phone_normalized", None)
        ident = f"...{phone[-4:]}" if phone and len(phone) >= 4 else f"#{item.id}"
        btn_text = f"{mark} {ident} | {getattr(item.category, 'title', '???')}"
        builder.button(text=btn_text, callback_data=AdminBatchCD(action="toggle", val=str(item.id)).pack())

    builder.adjust(1)

    builder.row(
        InlineKeyboardButton(text="🔘 Выделить страницу", callback_data=AdminBatchCD(action="select_all", val=str(page)).pack()),
        InlineKeyboardButton(text="⭕ Сбросить всё", callback_data=AdminBatchCD(action="clear").pack())
    )

    # Пагинация
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=AdminBatchCD(action="start", val=str(page-1)).pack()))
    nav_row.append(InlineKeyboardButton(text=f"{page+1}", callback_data="ignore"))
    if (page + 1) * 10 < total:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=AdminBatchCD(action="start", val=str(page+1)).pack()))
    if nav_row:
        builder.row(*nav_row)

    if selected_ids:
        builder.row(InlineKeyboardButton(text=f"🚀 ПРИМЕНИТЬ К ВЫБРАННЫМ ({len(selected_ids)})", callback_data=AdminBatchCD(action="apply").pack()))

    builder.row(InlineKeyboardButton(text="❮ В ДАШБОРД", callback_data="mod_back_dash"))
    return builder.as_markup()


def get_batch_status_kb() -> InlineKeyboardMarkup:
    """Выбор финального статуса для пачки."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ ЗАЧЁТ ВСЕМ", callback_data=AdminBatchCD(action="status", val="accepted"))
    builder.button(text="📦 НЕ СКАН", callback_data=AdminBatchCD(action="status", val="not_scan"))
    builder.button(text="❌ БРАК", callback_data=AdminBatchCD(action="status", val="reject"))
    builder.button(text="🚫 БЛОК", callback_data=AdminBatchCD(action="status", val="block"))
    builder.adjust(1, 3)
    builder.row(InlineKeyboardButton(text="❮ ОТМЕНА", callback_data=AdminBatchCD(action="start").pack()))
    return builder.as_markup()


def get_batch_reasons_kb(mode: str) -> InlineKeyboardMarkup:
    """Выбор причины отказа для пачки."""
    builder = InlineKeyboardBuilder()
    reasons = {
        "not_scan": ["Плохое фото", "Не QR-код", "Обрезано"],
        "reject": ["Не тот оператор", "Уже активен", "Ошибка данных"],
        "block": ["ФРОД / ДУБЛИКАТ", "Тестовый прогон", "Нарушение правил"]
    }

    for r in reasons.get(mode, ["Другое"]):
        builder.button(text=r, callback_data=AdminBatchCD(action="reason", val=f"{mode}:{r[:20]}").pack())

    builder.button(text="✍️ СВОЙ КОММЕНТАРИЙ", callback_data=AdminBatchCD(action="custom", val=mode).pack())
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="❮ НАЗАД", callback_data=AdminBatchCD(action="apply").pack()))
    return builder.as_markup()

def get_undo_kb(item_id: int) -> InlineKeyboardMarkup:
    """Всплывающая кнопка отката (живет 60 секунд)."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="↩️ ОТКАТИТЬ ДЕЙСТВИЕ (60с)",
        callback_data=AdminGradeCD(item_id=item_id, action="undo").pack()
    )
    builder.adjust(1)
    return builder.as_markup()