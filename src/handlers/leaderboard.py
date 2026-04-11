from __future__ import annotations

import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession

from src.keyboards.factory import SellerMenuCD, LeaderboardCD
from src.keyboards.leaderboard import get_leaderboard_kb
from src.services.admin_stats_service import AdminStatsService
from src.utils.media import media
from src.utils.ui_builder import GDPXRenderer

router = Router(name="leaderboard-new-router")
logger = logging.getLogger(__name__)
_renderer = GDPXRenderer()

@router.callback_query(SellerMenuCD.filter(F.action == "leaderboard"))
@router.callback_query(LeaderboardCD.filter())
async def on_leaderboard_open(
    callback: CallbackQuery, 
    callback_data: SellerMenuCD | LeaderboardCD, 
    session: AsyncSession
) -> None:
    """Отрисовка премиальной доски лидеров с баннером."""
    try:
        # 1. Параметры (берем топ-5 для максимальной компактности и эстетики)
        period = "all"
        if isinstance(callback_data, LeaderboardCD):
            period = callback_data.period

        # 2. Сбор данных
        stats_svc = AdminStatsService(session)
        top_sellers, _ = await stats_svc.get_leaderboard(period=period, page=0, page_size=5)

        # 3. Подготовка контента
        period_label = "За всё время" if period == "all" else "За последние 30 дней"
        text = _renderer.render_premium_leaderboard(top_sellers, period_label)
        banner = media.get("leaderboard.png")
        kb = get_leaderboard_kb(period)

        # 4. Обновление UI через edit_media (плавная смена без прыжков)
        try:
            await callback.message.edit_media(
                media=InputMediaPhoto(media=banner, caption=text, parse_mode="HTML"),
                reply_markup=kb
            )
        except Exception:
            # Если сообщение не медиа (например, нажали из текста), шлем новое фото
            await callback.message.answer_photo(
                photo=banner,
                caption=text,
                reply_markup=kb,
                parse_mode="HTML"
            )
            await callback.message.delete()

        await callback.answer()

    except Exception as e:
        logger.exception(f"Leaderboard premium error: {e}")
        await callback.answer("⚠️ Ошибка синхронизации", show_alert=True)

