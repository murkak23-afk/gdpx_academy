"""Seller module: aggregates all sub-routers into a single router."""

from aiogram import Router

from .info import router as _info_router
from .materials import router as _materials_router
from .profile import router as _profile_router
from .submission import router as _submission_router
from .keyboards import (
    get_back_to_main_kb,
    get_categories_kb,
    get_favorite_categories_kb,
    get_language_settings_kb,
    get_notification_settings_kb,
    get_seller_assets_folders_kb,
    get_seller_assets_items_kb,
    get_seller_item_view_kb,
    get_seller_main_kb,
    get_seller_payouts_kb,
    get_seller_profile_kb,
    get_seller_settings_kb,
    get_seller_stats_kb,
    get_upload_finish_kb,
)

router = Router(name="seller-router")

# Ordering matters for fallback resolution:
#   info      – callback/text handlers, no FSM conflicts
#   materials – own FSM states (edit_description, edit_media)
#   submission – main upload FSM (waiting_for_category, waiting_for_photo, …)
#   profile   – captcha + fallback (StateFilter(None)) must be last
router.include_router(_info_router)
router.include_router(_materials_router)
router.include_router(_submission_router)
router.include_router(_profile_router)
