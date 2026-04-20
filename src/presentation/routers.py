from aiogram import Router

# Импорт основных роутеров
from src.presentation.admin_panel.admin import router as admin_router
from src.presentation.admin_panel.admin.health import router as admin_health_router
from src.presentation.admin_panel.admin_delete_all_submissions import router as admin_delete_all_submissions_router
from src.presentation.admin_panel.cat_constructor import router as cat_constructor_router
from src.presentation.admin_panel.finance.payouts import router as finance_payouts_router
from src.presentation.common.inline_query import router as inline_query_router
from src.presentation.common.notifications import router as notifications_router
from src.presentation.common.global_handlers import router as global_handlers_router

# Импорт роутеров модерации
from src.presentation.admin_panel.moderation import router as moderation_root_router
from src.presentation.admin_panel.support.handlers import router as admin_support_router
from src.presentation.common.auto_fix import router as auto_fix_router
from src.presentation.qr_delivery.handlers import router as qr_delivery_router
from src.presentation.seller_portal.user_private import user_private_router


from src.presentation.seller_portal.seller.dynamics import router as seller_dynamics_router

def setup_routers() -> Router:
    root_router = Router()

    # 0. ВЫСШИЙ ПРИОРИТЕТ: Команды выдачи (только /qr)
    root_router.include_router(qr_delivery_router)
    
    # 1. СИСТЕМНЫЕ: Авто-фикс (текст в топиках) и Глобальные (отмена и т.д.)
    root_router.include_router(auto_fix_router)
    root_router.include_router(global_handlers_router)
    root_router.include_router(admin_support_router)

    # 1. ПРИОРИТЕТ: Личка и Профиль (включая /start)
    root_router.include_router(user_private_router)
    root_router.include_router(seller_dynamics_router) # НОВЫЙ РОУТЕР

    # 3. ПРИОРИТЕТ: Модерация
    root_router.include_router(moderation_root_router)

    # 4. ПРИОРИТЕТ: Админка
    root_router.include_router(admin_router)
    root_router.include_router(admin_health_router)
    root_router.include_router(finance_payouts_router)
    
    # Технические роутеры
    root_router.include_router(cat_constructor_router)
    root_router.include_router(admin_delete_all_submissions_router)
    
    # Inline-поиск
    root_router.include_router(inline_query_router)
    
    # Умные уведомления
    root_router.include_router(notifications_router)

    return root_router
