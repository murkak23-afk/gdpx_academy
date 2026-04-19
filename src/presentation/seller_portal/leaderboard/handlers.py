from __future__ import annotations

import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.utils.message_manager import MessageManager

from src.presentation.common.factory import SellerMenuCD, LeaderboardCD
from .keyboards import get_leaderboard_kb
from src.domain.moderation.admin_stats_service import AdminStatsService
from src.core.utils.media import media
from src.core.utils.ui_builder import GDPXRenderer

router = Router(name="leaderboard-new-router")
logger = logging.getLogger(__name__)
_renderer = GDPXRenderer()

@router.callback_query(SellerMenuCD.filter(F.action == "leaderboard"))
@router.callback_query(LeaderboardCD.filter())
async def on_leaderboard_open(
    callback: CallbackQuery, 
    callback_data: SellerMenuCD | LeaderboardCD, 
    session: AsyncSession,
    ui: MessageManager
):
    """Открытие доски лидеров с поддержкой пагинации и периодов."""
    try:
        # Определяем параметры
        period = "all"
        page = 0
        if isinstance(callback_data, LeaderboardCD):
            period = callback_data.period
            page = callback_data.page

        # Сбор данных
        stats_svc = AdminStatsService(session)
        top_list, total_count = await stats_svc.get_leaderboard(period=period, page=page, page_size=10)
        
        # Получаем данные текущего юзера
        user_rank = await stats_svc.get_user_rank_info(callback.from_user.id, period=period)

        # Получаем призовой фонд
        from src.database.models.web_control import LeaderboardSettings
        settings_res = await session.execute(select(LeaderboardSettings).limit(1))
        lb_settings = settings_res.scalar_one_or_none()
        prize_text = lb_settings.prize_text if lb_settings and lb_settings.prize_enabled else None

        # Рендеринг
        text = _renderer.render_leaderboard(
            period_label="ЗА ВСЁ ВРЕМЯ" if period == "all" else "ЗА 30 ДНЕЙ",
            top_list=top_list,
            user_rank=user_rank,
            page=page,
            total=total_count,
            prize_text=prize_text
        )
        
        banner = media.get("leaderboard.png")
        kb = await get_leaderboard_kb(period=period)

        await ui.display(event=callback, text=text, reply_markup=kb, photo=banner)
        await callback.answer()

    except Exception as e:
        logger.exception(f"Leaderboard error: {e}")
        await callback.answer("⚠️ Ошибка загрузки топа", show_alert=True)
