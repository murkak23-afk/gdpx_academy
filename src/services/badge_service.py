from __future__ import annotations

from src.database.models.user import User
from src.keyboards.constants import EMOJI_BADGE_STAR, EMOJI_BADGE_MEDAL, EMOJI_BADGE_FIRE, EMOJI_BADGE_CROWN

class BadgeService:
    @staticmethod
    def calculate_badges(user: User, dashboard_stats: dict) -> list[str]:
        """Рассчитывает список значков на основе статистики пользователя."""
        badges = []
        accepted = int(dashboard_stats.get("accepted", 0))
        total_paid = float(user.total_paid or 0)
        
        # 1. Значок за количество (Star -> Crown)
        if accepted >= 8000:
            badges.append(EMOJI_BADGE_CROWN)
        if accepted >= 3000:
            badges.append(EMOJI_BADGE_FIRE)
        if accepted >= 1000:
            badges.append(EMOJI_BADGE_MEDAL)
        if accepted >= 300:
            badges.append(EMOJI_BADGE_STAR)
            
        # 2. Индивидуальные значки из БД
        if user.badges:
            badges.extend(user.badges)
            
        # Возвращаем уникальные значки
        return list(dict.fromkeys(badges))
