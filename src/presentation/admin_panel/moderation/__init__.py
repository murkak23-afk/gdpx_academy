from __future__ import annotations

from aiogram import Router
from aiogram.utils.callback_answer import CallbackAnswerMiddleware

from .entry import router as entry_router
from .inspector import router as inspector_router
from .queue import router as queue_router
from .search import router as search_router
from .keyboards import (
    get_mod_dashboard_kb,
    get_mod_inspector_kb,
    get_mod_reasons_kb,
    get_qr_delivery_main_kb,
    get_qr_delivery_operators_kb,
    get_search_filters_kb,
    get_search_results_kb,
    get_seller_workspace_kb,
    get_sellers_queue_kb,
)

# Главный роутер модерации, который объединяет все под-роутеры (/a)
router = Router(name="admin-moderation-root")

# Подключаем автоматический ответ на колбэки один раз на весь корень модерации
router.callback_query.middleware(CallbackAnswerMiddleware())

# Включаем все дочерние роутеры
router.include_routers(
    entry_router,
    queue_router,
    inspector_router,
    search_router
)
