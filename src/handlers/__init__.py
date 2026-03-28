from aiogram import Router

from src.handlers.admin import router as admin_router
from src.handlers.inline_query import router as inline_query_router
from src.handlers.moderation import router as moderation_router
from src.handlers.seller import router as seller_router
from src.handlers.start import router as start_router
from src.handlers.withdrawal import router as withdrawal_router


def setup_routers() -> Router:
    root_router = Router(name="root-router")

    root_router.include_router(start_router)
    root_router.include_router(inline_query_router)  # 🆕 Inline Query Handler

    root_router.include_router(admin_router)
    root_router.include_router(seller_router)
    root_router.include_router(moderation_router)
    root_router.include_router(withdrawal_router)

    return root_router
