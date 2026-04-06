from aiogram import Router

# Импорт роутеров
from src.handlers.admin import router as admin_router
from src.handlers.admin_delete_all_submissions import router as admin_delete_all_submissions_router
from src.handlers.admin_grading import router as grading_router
from src.handlers.cat_constructor import router as cat_constructor_router
from src.handlers.group_queue import router as group_queue_router
from src.handlers.inline_query import router as inline_query_router
from src.handlers.moderation import router as moderation_router
from src.handlers.user_private import user_private_router


def setup_routers() -> Router:
    root_router = Router(name="root-router")

    # ПРИОРИТЕТ #1: Админка (должна быть первой, чтобы не перехватываться пользовательскими хендлерами)
    root_router.include_router(admin_router)
    root_router.include_router(grading_router)
    root_router.include_router(cat_constructor_router)
    
    # ПРИОРИТЕТ #2: Групповые чаты и модерация
    root_router.include_router(moderation_router)
    root_router.include_router(group_queue_router)
    
    # ПРИОРИТЕТ #3: Личные сообщения пользователя (самый "жадный" роутер)
    root_router.include_router(user_private_router)
    
    # Остальные технические
    root_router.include_router(inline_query_router)
    root_router.include_router(admin_delete_all_submissions_router)

    return root_router
