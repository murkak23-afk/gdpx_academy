from aiogram import Router

from src.handlers.admin.archive import (
    on_search_page,
    on_search_submission,
    on_submission_report,
)
from src.handlers.admin.menu import router as admin_menu_router
from src.handlers.admin.menu_core import (
    on_admin_fsm_step_back,
    on_admin_menu_interrupt_fsm,
    on_admin_panel,
    on_enter_admin_panel,
    on_exit_admin_panel,
)
from src.handlers.admin.payouts import on_daily_report, on_export_report, on_mark_paid

router = Router(name="admin-domain-router")
router.include_router(admin_menu_router)

__all__ = [
    "router",
    "on_admin_panel",
    "on_enter_admin_panel",
    "on_exit_admin_panel",
    "on_admin_fsm_step_back",
    "on_admin_menu_interrupt_fsm",
    "on_daily_report",
    "on_export_report",
    "on_mark_paid",
    "on_search_submission",
    "on_search_page",
    "on_submission_report",
]
