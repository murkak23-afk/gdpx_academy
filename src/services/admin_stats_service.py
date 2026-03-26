from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.category import Category
from src.database.models.enums import SubmissionStatus
from src.database.models.publication import Payout
from src.database.models.submission import Submission
from src.database.models.user import User


class AdminStatsService:
    """Агрегаты для раздела «Статистика» админ-панели."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def period_bounds(period: str) -> tuple[datetime, datetime]:
        """UTC: day = с начала суток; week = 7 дней; month = 30 дней."""

        now = datetime.now(timezone.utc)
        end = now
        if period == "day":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            start = now - timedelta(days=7)
        elif period == "month":
            start = now - timedelta(days=30)
        else:
            start = now - timedelta(days=7)
        return start, end

    async def count_incoming_submissions(self, start: datetime, end: datetime) -> int:
        stmt = select(func.count(Submission.id)).where(
            Submission.created_at >= start,
            Submission.created_at <= end,
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def count_by_status_reviewed(
        self,
        status: SubmissionStatus,
        start: datetime,
        end: datetime,
    ) -> int:
        stmt = select(func.count(Submission.id)).where(
            Submission.status == status,
            Submission.reviewed_at.is_not(None),
            Submission.reviewed_at >= start,
            Submission.reviewed_at <= end,
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def accepted_by_category(self, start: datetime, end: datetime) -> list[tuple[str, int]]:
        stmt = (
            select(Category.title, func.count(Submission.id))
            .join(Submission, Submission.category_id == Category.id)
            .where(
                Submission.status == SubmissionStatus.ACCEPTED,
                Submission.reviewed_at.is_not(None),
                Submission.reviewed_at >= start,
                Submission.reviewed_at <= end,
            )
            .group_by(Category.id, Category.title)
            .order_by(Category.title.asc())
        )
        rows = (await self._session.execute(stmt)).all()
        return [(str(t), int(c)) for t, c in rows]

    async def payout_rows_paginated(
        self,
        start: datetime,
        end: datetime,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, int | str | Decimal]], int]:
        """Продавцы с выплатами за период: сумма, число выплат."""

        subq = (
            select(
                Payout.user_id,
                func.coalesce(func.sum(Payout.amount), Decimal("0")).label("total_amt"),
                func.count(Payout.id).label("cnt"),
            )
            .where(
                Payout.created_at >= start,
                Payout.created_at <= end,
            )
            .group_by(Payout.user_id)
            .subquery()
        )
        count_stmt = select(func.count()).select_from(subq)
        total = int((await self._session.execute(count_stmt)).scalar_one() or 0)

        stmt = (
            select(User, subq.c.total_amt, subq.c.cnt)
            .join(subq, User.id == subq.c.user_id)
            .order_by(subq.c.total_amt.desc())
            .offset(page * page_size)
            .limit(page_size)
        )
        rows = (await self._session.execute(stmt)).all()
        out: list[dict[str, int | str | Decimal]] = []
        for user, total_amt, cnt in rows:
            out.append(
                {
                    "user_id": user.id,
                    "telegram_id": user.telegram_id,
                    "username": user.username or "",
                    "label": f"@{user.username}" if user.username else f"id:{user.telegram_id}",
                    "total_paid": total_amt,
                    "payout_count": int(cnt),
                }
            )
        return out, total
