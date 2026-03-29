from aiogram import Router

# Импортируем новый объединенный роутер
from src.handlers.user_private import user_private_router 
# Оставляем остальные технические роутеры
from src.handlers.admin import router as admin_router
from src.handlers.admin_grading import router as grading_router
from src.handlers.cat_constructor import router as cat_constructor_router
from src.handlers.inline_query import router as inline_query_router
from src.handlers.group_queue import router as group_queue_router
from src.handlers.moderation import router as moderation_router

def setup_routers() -> Router:
    root_router = Router(name="root-router")

    # Теперь вместо трех импортов используем один главный для пользователя
    root_router.include_router(user_private_router)
    
    # Оставляем системные роутеры
    root_router.include_router(inline_query_router)
    root_router.include_router(admin_router)
    root_router.include_router(grading_router)
    root_router.include_router(cat_constructor_router)
    root_router.include_router(moderation_router)
    root_router.include_router(group_queue_router)

    return root_router