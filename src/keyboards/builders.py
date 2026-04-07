from __future__ import annotations

from typing import Iterable, TYPE_CHECKING, Any
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from src.keyboards.factory import (
    NavCD, SellerMenuCD, SellerAssetCD, SellerItemCD, SellerItemCD,

    AdminMenuCD, AdminQueueCD, AdminInWorkCD, AdminPayoutCD, AdminGradeCD,
    CatConCD, SellerInfoCD, CatManageCD
)

if TYPE_CHECKING:
    from src.database.models.category import Category
    from src.database.models.submission import Submission

# --- СЕЛЛЕР ---
def get_seller_main_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❖ Залить eSIM", callback_data=SellerMenuCD(action="sell"))
    builder.button(text="🥋 ПРОФИЛЬ", callback_data=SellerMenuCD(action="profile"))
    builder.button(text="🗂 МОИ АКТИВЫ", callback_data=SellerMenuCD(action="assets"))
    builder.button(text="💼 ВЫПЛАТЫ", callback_data=SellerMenuCD(action="payouts"))
    builder.button(text="📜 КОДЕКС", callback_data=SellerMenuCD(action="info"))
    builder.button(text="🛡 SUPPORT CENTER", callback_data=SellerMenuCD(action="support"))
    builder.adjust(1, 1, 2, 2)
    return builder.as_markup()

def get_info_root_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📘 FAQ", callback_data=SellerMenuCD(action="faq"))
    builder.button(text="🧭 МАНУАЛЫ", callback_data=SellerMenuCD(action="manuals"))
    builder.button(text="❮ НАЗАД", callback_data=NavCD(to="menu"))
    builder.adjust(2, 1)
    return builder.as_markup()

def get_faq_list_kb(faq_cards: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for f in faq_cards:
        builder.button(text=f"{f.emoji} {f.title}", callback_data=SellerInfoCD(type="faq", id=f.id))
    builder.button(text="❮ В INFO", callback_data=SellerMenuCD(action="info"))
    builder.adjust(1)
    return builder.as_markup()

def get_manual_levels_kb(manual_levels: Iterable[Any]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for lvl in manual_levels:
        builder.button(text=f"{lvl.emoji} {lvl.title}", callback_data=SellerInfoCD(type="manual_lvl", id=lvl.id))
    builder.button(text="❮ В INFO", callback_data=SellerMenuCD(action="info"))
    builder.adjust(1)
    return builder.as_markup()

def get_manuals_in_level_kb(manuals: list[Any]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for m in manuals:
        builder.button(text=f"{m.emoji} {m.title}", callback_data=SellerInfoCD(type="manual_item", id=m.id))
    builder.button(text="❮ К УРОВНЯМ", callback_data=SellerMenuCD(action="manuals"))
    builder.adjust(1)
    return builder.as_markup()

def get_back_to_manual_level_kb(level_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❮ НАЗАД", callback_data=SellerInfoCD(type="manual_lvl", id=level_id))
    return builder.as_markup()

def get_back_to_info_kb(type: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    back_action = "faq" if type == "faq" else "manuals"
    builder.button(text="❮ НАЗАД", callback_data=SellerMenuCD(action=back_action))
    return builder.as_markup()

# --- АДМИН ---
def get_admin_main_kb() -> InlineKeyboardMarkup:
    """Главное меню администратора (только новые разделы)"""
    builder = InlineKeyboardBuilder()
    
    # Теперь только кнопка Модерации. Финансы — только через команды.
    builder.button(text="⚖️ МОДЕРАЦИЯ", callback_data=AdminMenuCD(section="moderation"))
    
    builder.adjust(1)
    return builder.as_markup()

# --- КОНСТРУКТОР КАТЕГОРИЙ ---
def get_catcon_main_kb() -> InlineKeyboardMarkup:
    """Главное меню админа по категориям (премиум-вариант)."""
    builder = InlineKeyboardBuilder()

    builder.button(
        text="📋 УПРАВЛЕНИЕ КАТЕГОРИЯМИ",
        callback_data=CatConCD(action="list").pack()
    )
    builder.button(
        text="➕ СОЗДАТЬ НОВУЮ КАТЕГОРИЮ",
        callback_data=CatConCD(action="start").pack()
    )

    builder.adjust(1)
    return builder.as_markup()

def get_catcon_options_kb(options: list[str], action: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for opt in options:
        builder.button(text=opt, callback_data=CatConCD(action=action, value=opt))
    builder.row(InlineKeyboardButton(text="🔴 ОТМЕНА", callback_data=CatConCD(action="cancel").pack()))
    builder.adjust(1)
    return builder.as_markup()

def get_catcon_confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🟢 СОЗДАТЬ", callback_data=CatConCD(action="confirm"))
    builder.button(text="🔴 ОТМЕНИТЬ", callback_data=CatConCD(action="cancel"))
    builder.adjust(1)
    return builder.as_markup()

def get_categories_kb(categories: Iterable[Category], cancel_to: str = "menu") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for cat in categories:
        builder.button(text=cat.title, callback_data=SellerAssetCD(category_id=cat.id))
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔴 ОТМЕНИТЬ", callback_data=NavCD(to=cancel_to).pack()))
    return builder.as_markup()

# --- РЕДАКТОР КАТЕГОРИЙ (АДМИН) ---
def get_cat_manage_list_kb(categories: list['Category']) -> InlineKeyboardMarkup:
    """Список всех категорий для управления (премиум-вид)."""
    builder = InlineKeyboardBuilder()

    for cat in categories:
        emoji = "🏮 " if getattr(cat, "is_priority", False) else ""
        status = "🟢" if cat.is_active else "🔴"
        title = f"{emoji}{status} {cat.title} | {cat.payout_rate} USDT"

        builder.button(
            text=title,
            callback_data=CatManageCD(action="view", cat_id=cat.id)
        )

    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(
            text="❮ НАЗАД В МЕНЮ",
            callback_data=NavCD(to="admin_menu").pack()   # если NavCD не работает — замени на CatConCD(action="list")
        )
    )
    return builder.as_markup()


def get_cat_manage_detail_kb(cat: 'Category') -> InlineKeyboardMarkup:
    """Детальное меню управления одной категорией."""
    builder = InlineKeyboardBuilder()

    # Кнопка включить/отключить
    active_text = "🔴 ОТКЛЮЧИТЬ" if cat.is_active else "🟢 ВКЛЮЧИТЬ"
    builder.button(
        text=active_text,
        callback_data=CatManageCD(action="toggle_active", cat_id=cat.id)
    )

    # Кнопка приоритета
    priority_text = "🏮 УБРАТЬ ПРИОРИТЕТ" if getattr(cat, "is_priority", False) else "🏮 В ПРИОРИТЕТ"
    builder.button(
        text=priority_text,
        callback_data=CatManageCD(action="toggle_priority", cat_id=cat.id)
    )

    # Изменить ставку
    builder.button(
        text="💰 ИЗМЕНИТЬ СТАВКУ",
        callback_data=CatManageCD(action="edit_price", cat_id=cat.id)
    )

    # Удалить
    builder.button(
        text="🗑 УДАЛИТЬ",
        callback_data=CatManageCD(action="confirm_delete", cat_id=cat.id)
    )

    builder.adjust(2, 1, 1)  # 2 кнопки в ряд, потом по одной

    # Кнопка назад к списку
    builder.row(
        InlineKeyboardButton(
            text="❮ К СПИСКУ",
            callback_data=CatConCD(action="list").pack()
        )
    )
    return builder.as_markup()


def get_cat_manage_confirm_delete_kb(cat_id: int) -> InlineKeyboardMarkup:
    """Подтверждение удаления."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⚠️ ДА, УДАЛИТЬ",
        callback_data=CatManageCD(action="delete", cat_id=cat_id)
    )
    builder.button(
        text="ОТМЕНИТЬ",
        callback_data=CatManageCD(action="view", cat_id=cat_id)
    )
    builder.adjust(1)
    return builder.as_markup()

def get_categories_kb(categories: list['Category'], cancel_to: str = "menu") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for cat in categories:
        emoji = "🏮 " if getattr(cat, "is_priority", False) else ""
        title = f"{emoji}{cat.title} | {cat.payout_rate} USDT"
        builder.button(text=title, callback_data=SellerAssetCD(category_id=cat.id))
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔴 Отменить", callback_data=NavCD(to=cancel_to).pack()))
    return builder.as_markup()

def get_upload_finish_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ ПОДТВЕРДИТЬ ИНТЕГРАЦИЮ", callback_data="upload_finish")
    builder.button(text="🗑 ОТМЕНИТЬ ВСЁ", callback_data="upload_cancel")
    builder.adjust(1)
    return builder.as_markup()
    

def get_seller_assets_folders_kb(folders: list[dict], best_cat_id: int | None) -> InlineKeyboardMarkup:
      """Клавиатура папок активов с умной сортировкой и выделением лучших."""
      builder = InlineKeyboardBuilder()

 
      sorted_folders = sorted(folders, key=lambda f: (f['category_id'] != best_cat_id, -f['total']))

      for f in sorted_folders:
          title = f"{f['title']}"
          if f['category_id'] == best_cat_id:
              title = f"🏆 {title} 🔥"
          else:
              title = f"🗂 {title}"

          btn_text = f"{title} [{f['total']} шт]"
          builder.button(text=btn_text, callback_data=SellerAssetCD(category_id=f['category_id']).pack())

      builder.adjust(1)
      builder.row(InlineKeyboardButton(text="❮ Назад в меню", callback_data=NavCD(to="menu").pack()))
      return builder.as_markup()

def get_seller_assets_items_kb(items: list, category_id: int, current_page: int, total_items: int, current_filter: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    filters = [
        ("📦 Все", "all"), 
        ("⏳ Ожидает", "pending"), 
        ("🟢 Зачтено", "accepted"), 
        ("🔴 Брак", "rejected")
    ]
    
    filter_row = []
    for label, key in filters:
        text = f"▪️ {label}" if key == current_filter else label
        filter_row.append(InlineKeyboardButton(
            text=text, 
            callback_data=SellerAssetCD(category_id=category_id, page=0, filter_key=key).pack()
        ))
    
    builder.row(*filter_row[:2])
    builder.row(*filter_row[2:])
    
    for item in items:
        status_val = item.status.value
        status_emoji = "⏳" if status_val == "pending" else "🟠" if status_val == "in_review" else "🟢" if status_val == "accepted" else "🔴"
        price = getattr(item, "fixed_payout_rate", "0.0")
        
        phone = getattr(item, "phone_normalized", None)
        ident = f"...{phone[-4:]}" if phone and len(phone) >= 4 else f"#{item.id}"
        
        text = f"{status_emoji} {ident} | {price} USDT"
        builder.button(text=text, callback_data=SellerItemCD(item_id=item.id, action="view").pack())
    
    builder.adjust(2, 2, 1, 1, 1, 1, 1, 1, 1)
    
    nav_row = []
    if current_page > 0:
        nav_row.append(InlineKeyboardButton(
            text="⬅️", 
            callback_data=SellerAssetCD(category_id=category_id, page=current_page-1, filter_key=current_filter).pack()
        ))
    else:
        nav_row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
        
    nav_row.append(InlineKeyboardButton(text=f"Стр. {current_page + 1}", callback_data="ignore"))
    
    if (current_page + 1) * 7 < total_items:
        nav_row.append(InlineKeyboardButton(
            text="➡️", 
            callback_data=SellerAssetCD(category_id=category_id, page=current_page+1, filter_key=current_filter).pack()
        ))
    else:
        nav_row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
        
    if total_items > 0:
        builder.row(*nav_row)
        
    builder.row(InlineKeyboardButton(
        text="❮ К списку кластеров", 
        callback_data=SellerMenuCD(action="assets").pack()
    ))
    return builder.as_markup()

def get_seller_item_view_kb(item_id: int, category_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 ОТОЗВАТЬ АКТИВ",
                   callback_data=SellerItemCD(item_id=item_id,
                                              action="delete").pack())
    builder.button(text="❮ НАЗАД К КЛАСТЕРУ",                      
                   callback_data=SellerAssetCD(category_id=category_id).pack())       
    builder.adjust(1)                                              
    return builder.as_markup()   