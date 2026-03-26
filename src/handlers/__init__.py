from aiogram import Router

from src.handlers.admin import router as admin_router
from src.handlers.admin_stats import router as admin_stats_router
from src.handlers.moderation import router as moderation_router
from src.handlers.seller import router as seller_router
from src.handlers.start import router as start_router


def setup_routers() -> Router:
    """Собирает корневой роутер приложения."""

    root_router = Router(name="root-router")
    root_router.include_router(start_router)
    # Админ раньше селлера: пункты меню (в т.ч. «Запросы») не должны уходить в FSM «Продать eSIM».
    root_router.include_router(admin_router)
    root_router.include_router(admin_stats_router)
    root_router.include_router(seller_router)
    root_router.include_router(moderation_router)
    return root_router
