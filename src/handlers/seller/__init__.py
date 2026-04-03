"""Seller module: aggregates all sub-routers into a single router."""

from aiogram import Router

from src.handlers.seller.info import router as _info_router
from src.handlers.seller.materials import router as _materials_router
from src.handlers.seller.profile import router as _profile_router
from src.handlers.seller.submission import router as _submission_router

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
