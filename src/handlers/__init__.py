from aiogram import Router

# Импорт основных роутеров
from src.handlers.admin import router as admin_router
from src.handlers.admin.health import router as admin_health_router
from src.handlers.admin_delete_all_submissions import router as admin_delete_all_submissions_router
from src.handlers.cat_constructor import router as cat_constructor_router
from src.handlers.group_queue import router as group_queue_router
from src.handlers.inline_query import router as inline_query_router
from src.handlers.user_private import user_private_router
from src.handlers.finance.payouts import router as finance_payouts_router

# Импорт роутеров модерации
from src.handlers.moderation import router as moderation_root_router


def setup_routers() -> Router:
    root_router = Router()

    # 1. ПРИОРИТЕТ: Модерация (единый роутер со всеми под-модулями /a)
    root_router.include_router(moderation_root_router)

    # 2. ПРИОРИТЕТ: Админка
    root_router.include_router(admin_router)
    root_router.include_router(admin_health_router)
    root_router.include_router(finance_payouts_router)
    # Технические роутеры
    root_router.include_router(cat_constructor_router)
    root_router.include_router(group_queue_router)
    root_router.include_router(admin_delete_all_submissions_router)

    # 3. Пользовательская часть
    root_router.include_router(user_private_router)
    
    # Inline-поиск
    root_router.include_router(inline_query_router)

    return root_router