from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.models.submission import Submission
from src.database.models.enums import SubmissionStatus

@dataclass
class RankInfo:
    name: str
    bonus_percent: Decimal
    threshold: int
    emoji: str

RANKS = [
    RankInfo("Стажёр", Decimal("0"), 0, "🪪"),
    RankInfo("Партнёр", Decimal("1.0"), 50, "🤝"),
    RankInfo("Резидент", Decimal("2.5"), 300, "💼"),
    RankInfo("Инвестор", Decimal("4.0"), 1000, "♟"),
    RankInfo("Акционер Синдиката", Decimal("6.0"), 1500, "🌐"),
]

class RankService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_user_approved_count(self, user_id: int) -> int:
        stmt = (
            select(func.count(Submission.id))
            .where(
                Submission.user_id == user_id,
                Submission.status == SubmissionStatus.ACCEPTED.value
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def get_user_rank(self, user_id: int) -> RankInfo:
        approved_count = await self.get_user_approved_count(user_id)
        
        current_rank = RANKS[0]
        for rank in RANKS:
            if approved_count >= rank.threshold:
                current_rank = rank
            else:
                break
        return current_rank

    def calculate_bonus_amount(self, base_amount: Decimal, rank: RankInfo) -> Decimal:
        if rank.bonus_percent <= 0:
            return base_amount
        
        bonus = base_amount * (rank.bonus_percent / Decimal("100"))
        # Округляем до 2 знаков для USDT
        return (base_amount + bonus).quantize(Decimal("0.01"))
