from aiogram import Router

from src.handlers.admin.archive import (
    router as admin_archive_router,
    on_search_page,
    on_search_submission,
    on_submission_report,
)
from src.handlers.admin.mailing import (
    router as admin_mailing_router,
    on_broadcast_start,
)
from src.handlers.admin.menu import router as admin_menu_router
from src.handlers.admin.menu_core import (
    on_admin_fsm_step_back,
    on_admin_menu_interrupt_fsm,
    on_admin_panel,
    on_enter_admin_panel,
    on_exit_admin_panel,
)
from src.handlers.admin.payouts import (
    router as admin_payouts_router,
    on_daily_report,
    on_export_report,
    on_mark_paid,
)
from src.handlers.admin.stats import router as admin_stats_router

router = Router(name="admin-domain-router")
router.include_router(admin_menu_router)
router.include_router(admin_stats_router)
router.include_router(admin_mailing_router)
router.include_router(admin_archive_router)
router.include_router(admin_payouts_router)

__all__ = [
    "router",
    "on_admin_panel",
    "on_enter_admin_panel",
    "on_exit_admin_panel",
    "on_admin_fsm_step_back",
    "on_admin_menu_interrupt_fsm",
    "on_broadcast_start",
    "on_daily_report",
    "on_export_report",
    "on_mark_paid",
    "on_search_submission",
    "on_search_page",
    "on_submission_report",
]
