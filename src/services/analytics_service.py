"""Global Analytics Service — Stage 11.

Provides a single aggregated financial/operational report built from
read-only SQL queries against the current request-scoped session.

All queries are fire-and-forget SELECTs: no writes, no locks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.enums import SubmissionStatus
from src.database.models.submission import Submission
from src.database.models.user import User

_REJECTED_STATUSES = (
    SubmissionStatus.REJECTED,
    SubmissionStatus.BLOCKED,
    SubmissionStatus.NOT_A_SCAN,
)


@dataclass(slots=True)
class AnalyticsReport:
    """Immutable snapshot of the global system report."""

    total_turnover: Decimal
    """Cumulative USDT paid out to all agents historically (sum of users.total_paid)."""

    turnover_24h: Decimal
    """eSIM payouts accepted in the last 24 hours (sum of submissions.accepted_amount)."""

    esim_accepted: int
    """Total eSIM submissions ever accepted."""

    esim_rejected: int
    """Total eSIM submissions rejected/blocked/not-a-scan (all time)."""

    pending_payouts_sum: Decimal
    """Total USDT currently owed to active agents (sum of users.pending_balance)."""

    generated_at: datetime
    """UTC timestamp when this report was assembled."""


class AnalyticsService:
    """Read-only aggregation service for global financial/operational metrics."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_global_report(self) -> AnalyticsReport:
        """Execute all metric queries concurrently and return a report snapshot. Safe fallback on errors."""
        import asyncio

        results = await asyncio.gather(
            self._total_turnover(),
            self._turnover_24h(),
            self._esim_count(SubmissionStatus.ACCEPTED),
            self._esim_rejected_count(),
            self._pending_payouts_sum(),
            return_exceptions=True
        )
        def safe(val, default):
            return default if isinstance(val, Exception) else val

        return AnalyticsReport(
            total_turnover=safe(results[0], Decimal("0")),
            turnover_24h=safe(results[1], Decimal("0")),
            esim_accepted=safe(results[2], 0),
            esim_rejected=safe(results[3], 0),
            pending_payouts_sum=safe(results[4], Decimal("0")),
            generated_at=datetime.now(timezone.utc),
        )

    # ── Private query methods ──────────────────────────────────────────────

    async def _total_turnover(self) -> Decimal:
        """SUM(users.total_paid) — all-time cumulative paid to agents."""
        stmt = select(func.coalesce(func.sum(User.total_paid), 0))
        result = await self._session.execute(stmt)
        return Decimal(result.scalar_one() or 0)

    async def _turnover_24h(self) -> Decimal:
        """SUM(submissions.accepted_amount) WHERE reviewed_at >= now - 24h."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        stmt = select(
            func.coalesce(func.sum(Submission.accepted_amount), 0)
        ).where(
            Submission.status == SubmissionStatus.ACCEPTED,
            Submission.reviewed_at >= cutoff,
            Submission.is_archived == False,
        )
        result = await self._session.execute(stmt)
        return Decimal(result.scalar_one() or 0)

    async def _esim_count(self, status: SubmissionStatus) -> int:
        """COUNT(*) submissions with a given status (excluding archived)."""
        stmt = select(func.count(Submission.id)).where(
            Submission.status == status,
            Submission.is_archived == False,
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def _esim_rejected_count(self) -> int:
        """COUNT(*) submissions with any rejection-family status (excluding archived)."""
        stmt = select(func.count(Submission.id)).where(
            Submission.status.in_(_REJECTED_STATUSES),
            Submission.is_archived == False,
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def _pending_payouts_sum(self) -> Decimal:
        """SUM(users.pending_balance) for all active agents."""
        stmt = select(
            func.coalesce(func.sum(User.pending_balance), 0)
        ).where(User.is_active.is_(True))
        result = await self._session.execute(stmt)
        return Decimal(result.scalar_one() or 0)
