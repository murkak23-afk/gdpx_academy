from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.handlers.admin.archive import router as admin_archive_router
from src.handlers.admin.mailing import router as admin_mailing_router
from src.handlers.admin.menu import router as admin_menu_router
from src.handlers.admin.payouts import router as admin_payouts_router
from src.handlers.admin.stats import router as admin_stats_router

# Главный админ-роутер
router = Router(name="admin-domain-router")

@router.message(Command("a"))
async def entry_point_admin(message: Message, session: AsyncSession) -> None:
    """Точка входа /a — без фильтров на уровне роутера, проверка внутри хендлера."""
    from src.handlers.admin_menu import cmd_admin_panel
    await cmd_admin_panel(message, session)

# Подключаем остальные части
router.include_router(admin_menu_router)
router.include_router(admin_stats_router)
router.include_router(admin_mailing_router)
router.include_router(admin_archive_router)
router.include_router(admin_payouts_router)

__all__ = ["router"]
