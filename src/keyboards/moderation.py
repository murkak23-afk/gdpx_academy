"""Silver Sakura — Клавиатуры модерации."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from src.keyboards.base import PremiumBuilder
from src.keyboards.constants import *
from src.callbacks.moderation import AdminQueueCD, AdminGradeCD, AdminBatchCD

def get_mod_dashboard_kb(total_pending: int, my_in_work: int) -> InlineKeyboardMarkup:
    builder = PremiumBuilder()
    
    if my_in_work > 0:
        builder.primary(f"🔥 ПРОДОЛЖИТЬ РАБОТУ ({my_in_work})", "mod_my_work_folder")
    
    builder.button(f"🚀 ОЧЕРЕДЬ АКТИВОВ ({total_pending})", AdminQueueCD(action="start"))
    builder.button(f"{EMOJI_SEARCH} ПОИСК ПО НОМЕРУ", "mod_search")
    builder.button(f"{EMOJI_BOX} BATCH-МАСТЕР", AdminBatchCD(action="start", val="0"))
    
    builder.adjust(1)
    builder.back("admin_menu", "ВЕРНУТЬСЯ В МЕНЮ")
    return builder.as_markup()

def get_inspector_kb(item_id: int, remaining: int) -> InlineKeyboardMarkup:
    builder = PremiumBuilder()
    builder.primary(f"✅ ЗАЧЁТ (Осталось: {remaining})", AdminGradeCD(item_id=item_id, action="accept"))
    
    builder.button(f"{EMOJI_BOX} НЕ СКАН", AdminGradeCD(item_id=item_id, action="not_scan"))
    builder.button(f"{EMOJI_REJECT} БРАК", AdminGradeCD(item_id=item_id, action="reject"))
    builder.button(f"🚫 БЛОК", AdminGradeCD(item_id=item_id, action="block"))
    
    builder.adjust(1, 3)
    builder.button("⏸ ПРИОСТАНОВИТЬ", "mod_pause")
    return builder.as_markup()
