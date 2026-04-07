"""Leaderboard queries: weekly top-5 by accepted submissions + user rank."""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, over, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.cache import cached
from src.core.config import get_settings
from src.database.models.leaderboard_settings import LeaderboardSettings
from src.database.models.submission import Submission
from src.database.models.user import User

# Allowed pseudonym characters: letters (any script), digits, underscore, hyphen.
_PSEUDONYM_RE = re.compile(r"^[\w\-]{2,32}$", re.UNICODE)


def validate_pseudonym(value: str) -> str | None:
    """Returns cleaned pseudonym if valid, else None."""
    cleaned = value.strip()
    if not _PSEUDONYM_RE.match(cleaned):
        return None
    return cleaned


def _week_bounds() -> tuple[date, date]:
    """Returns (monday, sunday) for the current ISO week."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def week_number() -> int:
    return date.today().isocalendar()[1]


class LeaderboardService:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    @cached(ttl=lambda: get_settings().cache_ttl_leaderboard)
    async def get_top5(self) -> list[dict]:


        stmt = (
            select(
                User.id.label("user_id"),
                User.pseudonym.label("pseudonym"),
                User.total_paid.label("turnover"),
                func.count(Submission.id).label("score"),
            )
            .join(Submission, Submission.user_id == User.id)
            .where(
                Submission.status == "accepted",
                func.date(Submission.created_at) >= monday,
                func.date(Submission.created_at) <= sunday,
                User.pseudonym.isnot(None),
            )
            .group_by(User.id, User.pseudonym, User.total_paid)
            .order_by(func.count(Submission.id).desc())
            .limit(5)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            {
                "user_id": r.user_id,
                "pseudonym": r.pseudonym,
                "score": r.score,
                "turnover": r.turnover or Decimal("0"),
            }
            for r in rows
        ]

    @cached(ttl=lambda: get_settings().cache_ttl_leaderboard)
    async def get_user_rank(self, user_id: int) -> tuple[int, int]:
        """Returns (rank, score) for the given user this week.

        Rank is 1-based. Returns (0, 0) if user has no accepted this week.
        Uses a single query with RANK() OVER instead of two round-trips.
        """
        monday, sunday = _week_bounds()

        score_expr = func.count(Submission.id)
        # RANK() OVER (ORDER BY COUNT(*) DESC) вычисляется PostgreSQL
        # после GROUP BY над уже агрегированными строками.
        rank_expr = over(func.rank(), order_by=score_expr.desc())

        inner = (
            select(
                Submission.user_id.label("uid"),
                score_expr.label("score"),
                rank_expr.label("rank"),
            )
            .where(
                Submission.status == "accepted",
                func.date(Submission.created_at) >= monday,
                func.date(Submission.created_at) <= sunday,
            )
            .group_by(Submission.user_id)
            .subquery()
        )

        stmt = select(inner.c.score, inner.c.rank).where(inner.c.uid == user_id)
        row = (await self._session.execute(stmt)).one_or_none()
        if row is None:
            return 0, 0
        return int(row.rank), int(row.score)

    async def get_user_turnover(self, user_id: int) -> Decimal:
        """Returns all-time total_paid for the user (internal DB id)."""
        row = (
            await self._session.execute(
                select(User.total_paid).where(User.id == user_id)
            )
        ).scalar_one_or_none()
        return row if row is not None else Decimal("0.00")


class LeaderboardSettingsService:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def get(self) -> LeaderboardSettings:
        """Gets the single settings row, creating it if missing."""
        stmt = select(LeaderboardSettings).limit(1)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            row = LeaderboardSettings(prize_enabled=False, prize_text=None)
            self._session.add(row)
            await self._session.flush()
        return row

    async def toggle_prize(self) -> bool:
        """Toggles prize_enabled. Returns the new value."""
        row = await self.get()
        row.prize_enabled = not row.prize_enabled
        await self._session.flush()
        return row.prize_enabled

    async def set_prize_text(self, text: str) -> None:
        row = await self.get()
        row.prize_text = text.strip()[:512]
        await self._session.flush()
