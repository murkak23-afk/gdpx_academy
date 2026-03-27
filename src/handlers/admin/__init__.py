from aiogram import Router

from src.handlers.admin.archive import (
    on_archive_help,
    on_archive_page,
    on_archive_search,
    on_search_page,
    on_search_submission,
    on_submission_report,
)
from src.handlers.admin.categories import (
    on_admin_categories_actions,
    on_admin_categories_menu,
    on_category_add_description,
    on_category_add_payout_rate,
    on_category_add_photo_photo,
    on_category_add_photo_text,
    on_category_add_title,
    on_category_add_total_limit,
    on_category_edit_value,
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
from src.handlers.admin.requests import (
    on_requests_menu,
    on_requests_quota_line,
    on_requests_ui,
    open_requests_section,
)
from src.handlers.admin.stats import router as admin_stats_router

router = Router(name="admin-domain-router")
router.include_router(admin_menu_router)
router.include_router(admin_stats_router)

__all__ = [
    "router",
    "on_admin_panel",
    "on_enter_admin_panel",
    "on_exit_admin_panel",
    "on_admin_fsm_step_back",
    "on_admin_menu_interrupt_fsm",
    "open_requests_section",
    "on_requests_menu",
    "on_requests_ui",
    "on_requests_quota_line",
    "on_daily_report",
    "on_export_report",
    "on_mark_paid",
    "on_admin_categories_menu",
    "on_admin_categories_actions",
    "on_category_add_title",
    "on_category_add_payout_rate",
    "on_category_add_total_limit",
    "on_category_add_description",
    "on_category_add_photo_photo",
    "on_category_add_photo_text",
    "on_category_edit_value",
    "on_archive_help",
    "on_archive_search",
    "on_archive_page",
    "on_search_submission",
    "on_search_page",
    "on_submission_report",
]
