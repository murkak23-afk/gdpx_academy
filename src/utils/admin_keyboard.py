from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from src.keyboards.inline import admin_main_inline_keyboard
from src.keyboards.reply import admin_main_menu_keyboard
from src.services.admin_service import AdminService


async def build_admin_main_menu_keyboard(session: AsyncSession, telegram_id: int) -> ReplyKeyboardMarkup:
    show = await AdminService(session=session).can_access_payout_finance(telegram_id)
    return admin_main_menu_keyboard(show_payout_finance=show)


async def build_admin_main_inline_keyboard(session: AsyncSession, telegram_id: int) -> InlineKeyboardMarkup:
    show = await AdminService(session=session).can_access_payout_finance(telegram_id)
    return admin_main_inline_keyboard(show_payout_finance=show)
