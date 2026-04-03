from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.stats_epoch import get_stats_epoch
from src.database.models.category import Category
from src.database.models.enums import SubmissionStatus
from src.database.models.publication import Payout
from src.database.models.submission import Submission
from src.database.models.user import User


class AdminStatsService:
    """Агрегаты для раздела «Статистика» админ-панели."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._epoch = get_stats_epoch()

    def _effective_start(self, start: datetime) -> datetime:
        """Returns max(start, epoch) to honour stats reset."""
        if self._epoch is not None and self._epoch > start:
            return self._epoch
        return start

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

    @staticmethod
    def month_bounds_utc(year: int, month: int) -> tuple[datetime, datetime]:
        """UTC-границы календарного месяца [start, end)."""

        start = datetime(year=year, month=month, day=1, tzinfo=timezone.utc)
        if month == 12:
            end = datetime(year=year + 1, month=1, day=1, tzinfo=timezone.utc)
        else:
            end = datetime(year=year, month=month + 1, day=1, tzinfo=timezone.utc)
        return start, end

    async def daily_sim_stats_for_month(self, year: int, month: int) -> list[dict[str, int | date]]:
        """Дневная статистика за месяц по SIM: вход, зачёт и виды брака."""

        start, end = self.month_bounds_utc(year, month)
        effective_start = self._effective_start(start)
        days = (end.date() - start.date()).days

        result: dict[date, dict[str, int | date]] = {}
        for offset in range(days):
            d = start.date() + timedelta(days=offset)
            result[d] = {
                "date": d,
                "incoming": 0,
                "accepted": 0,
                "rejected": 0,
                "blocked": 0,
                "not_a_scan": 0,
            }

        incoming_stmt = (
            select(
                func.date(Submission.created_at).label("d"),
                func.count(Submission.id).label("cnt"),
            )
            .where(
                Submission.created_at >= effective_start,
                Submission.created_at < end,
            )
            .group_by(func.date(Submission.created_at))
        )
        for d, cnt in (await self._session.execute(incoming_stmt)).all():
            if d in result:
                result[d]["incoming"] = int(cnt or 0)

        reviewed_statuses = [
            (SubmissionStatus.ACCEPTED, "accepted"),
            (SubmissionStatus.REJECTED, "rejected"),
            (SubmissionStatus.BLOCKED, "blocked"),
            (SubmissionStatus.NOT_A_SCAN, "not_a_scan"),
        ]
        for status, key in reviewed_statuses:
            stmt = (
                select(
                    func.date(Submission.reviewed_at).label("d"),
                    func.count(Submission.id).label("cnt"),
                )
                .where(
                    Submission.reviewed_at.is_not(None),
                    Submission.reviewed_at >= effective_start,
                    Submission.reviewed_at < end,
                    Submission.status == status,
                )
                .group_by(func.date(Submission.reviewed_at))
            )
            for d, cnt in (await self._session.execute(stmt)).all():
                if d in result:
                    result[d][key] = int(cnt or 0)

        return [result[d] for d in sorted(result.keys())]

    async def count_incoming_submissions(self, start: datetime, end: datetime) -> int:
        effective = self._effective_start(start)
        stmt = select(func.count(Submission.id)).where(
            Submission.created_at >= effective,
            Submission.created_at <= end,
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def count_by_status_reviewed(
        self,
        status: SubmissionStatus,
        start: datetime,
        end: datetime,
    ) -> int:
        effective = self._effective_start(start)
        stmt = select(func.count(Submission.id)).where(
            Submission.status == status,
            Submission.reviewed_at.is_not(None),
            Submission.reviewed_at >= effective,
            Submission.reviewed_at <= end,
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def accepted_by_category(self, start: datetime, end: datetime) -> list[tuple[str, int, Decimal]]:
        effective = self._effective_start(start)
        stmt = (
            select(
                Category.title,
                func.count(Submission.id),
                func.coalesce(func.sum(Submission.accepted_amount), Decimal("0.00")),
            )
            .join(Submission, Submission.category_id == Category.id)
            .where(
                Submission.status == SubmissionStatus.ACCEPTED,
                Submission.reviewed_at.is_not(None),
                Submission.reviewed_at >= effective,
                Submission.reviewed_at <= end,
            )
            .group_by(Category.id, Category.title)
            .order_by(Category.title.asc())
        )
        rows = (await self._session.execute(stmt)).all()
        return [(str(t), int(c), Decimal(a)) for t, c, a in rows]

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
                Payout.created_at >= self._effective_start(start),
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
                    "label": f"@{user.username}" if user.username else f"@{user.telegram_id}",
                    "total_paid": total_amt,
                    "payout_count": int(cnt),
                }
            )
        return out, total

    async def avg_accept_amount(self, start: datetime, end: datetime) -> Decimal:
        effective = self._effective_start(start)
        stmt = select(func.avg(Submission.accepted_amount)).where(
            Submission.status == SubmissionStatus.ACCEPTED,
            Submission.reviewed_at.is_not(None),
            Submission.reviewed_at >= effective,
            Submission.reviewed_at <= end,
        )
        val = (await self._session.execute(stmt)).scalar_one_or_none()
        return Decimal(val or 0).quantize(Decimal("0.01"))

    async def top_sellers_by_accept_amount(
        self,
        start: datetime,
        end: datetime,
        *,
        limit: int = 5,
    ) -> list[tuple[str, Decimal, int]]:
        effective = self._effective_start(start)
        stmt = (
            select(
                User.username,
                User.telegram_id,
                func.coalesce(func.sum(Submission.accepted_amount), Decimal("0.00")).label("amt"),
                func.count(Submission.id).label("cnt"),
            )
            .join(Submission, Submission.user_id == User.id)
            .where(
                Submission.status == SubmissionStatus.ACCEPTED,
                Submission.reviewed_at.is_not(None),
                Submission.reviewed_at >= effective,
                Submission.reviewed_at <= end,
            )
            .group_by(User.id, User.username, User.telegram_id)
            .order_by(func.sum(Submission.accepted_amount).desc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        out: list[tuple[str, Decimal, int]] = []
        for username, telegram_id, amt, cnt in rows:
            label = f"@{username}" if username else f"@{telegram_id}"
            out.append((label, Decimal(amt or 0), int(cnt or 0)))
        return out
