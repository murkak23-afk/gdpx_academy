from __future__ import annotations
from aiogram import Router
from aiogram.utils.callback_answer import CallbackAnswerMiddleware

from .entry import router as entry_router
from .queue import router as queue_router
from .inspector import router as inspector_router
from .search import router as search_router
from .batch import router as batch_router

# Главный роутер модерации, который объединяет все под-роутеры (/a)
router = Router(name="admin-moderation-root")

# Подключаем автоматический ответ на колбэки один раз на весь корень модерации
router.callback_query.middleware(CallbackAnswerMiddleware())

# Включаем все дочерние роутеры
router.include_routers(
    entry_router,
    queue_router,
    inspector_router,
    search_router,
    batch_router
)
