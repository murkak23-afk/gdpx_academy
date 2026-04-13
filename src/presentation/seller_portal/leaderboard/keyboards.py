from aiogram.types import InlineKeyboardMarkup

from src.core.cache.keyboard_cache import cached_keyboard
from src.presentation.common.base import PremiumBuilder
from src.presentation.common.factory import LeaderboardCD, SellerMenuCD


@cached_keyboard(ttl=600)
def get_leaderboard_kb(period: str) -> InlineKeyboardMarkup:
    """Улучшенная премиальная клавиатура для доски лидеров."""
    builder = PremiumBuilder()
    
    # Кнопки периодов
    all_btn = "✨ ЗА ВСЁ ВРЕМЯ" if period == "all" else "♾ ЗА ВСЁ ВРЕМЯ"
    d30_btn = "✨ ЗА 30 ДНЕЙ" if period == "30d" else "📅 ЗА 30 ДНЕЙ"
    
    builder.button(all_btn, LeaderboardCD(period="all", page=0))
    builder.button(d30_btn, LeaderboardCD(period="30d", page=0))
    
    builder.adjust(2)
    builder.back(SellerMenuCD(action="main"), "В ГЛАВНОЕ МЕНЮ")
    return builder.as_markup()
