from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.enums import SubmissionStatus
from src.database.models.publication import Payout
from src.database.models.submission import Submission
from src.database.models.user import User


class BillingService:
    """Сервис отчетов и фиксации выплат."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_daily_report_rows(self) -> list[dict[str, int | str | Decimal]]:
        """Возвращает строки ежедневного отчета по пользователям с балансом к выплате."""

        day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        accepted_stmt = (
            select(
                Submission.user_id,
                func.count(Submission.id).label("accepted_count"),
            )
            .where(
                Submission.status == SubmissionStatus.ACCEPTED,
                Submission.reviewed_at >= day_start,
            )
            .group_by(Submission.user_id)
        )
        accepted_rows = (await self._session.execute(accepted_stmt)).all()
        accepted_map: dict[int, int] = {int(row.user_id): int(row.accepted_count) for row in accepted_rows}

        users_stmt = select(User).where(User.pending_balance > Decimal("0.00")).order_by(User.id.asc())
        users = list((await self._session.execute(users_stmt)).scalars().all())

        report_rows: list[dict[str, int | str | Decimal]] = []
        for user in users:
            report_rows.append(
                {
                    "user_id": user.id,
                    "telegram_id": user.telegram_id,
                    "username": f"@{user.username}" if user.username else f"id:{user.telegram_id}",
                    "accepted_count": accepted_map.get(user.id, 0),
                    "to_pay": Decimal(user.pending_balance),
                }
            )
        return report_rows

    async def mark_user_paid(self, user_id: int, paid_by_admin_id: int) -> Payout | None:
        """Сбрасывает pending_balance и создает запись выплаты."""

        user = await self._session.get(User, user_id)
        if user is None:
            return None

        amount = Decimal(user.pending_balance)
        if amount <= Decimal("0.00"):
            return None

        day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        accepted_stmt = select(func.count(Submission.id)).where(
            Submission.user_id == user.id,
            Submission.status == SubmissionStatus.ACCEPTED,
            Submission.reviewed_at >= day_start,
        )
        accepted_count = int((await self._session.execute(accepted_stmt)).scalar_one())

        payout = Payout(
            user_id=user.id,
            amount=amount,
            accepted_count=accepted_count,
            period_key=day_start.date().isoformat(),
            paid_by_admin_id=paid_by_admin_id,
            note="manual_daily_report",
        )
        user.pending_balance = Decimal("0.00")
        user.total_paid = Decimal(user.total_paid) + amount

        self._session.add(payout)
        await self._session.commit()
        await self._session.refresh(payout)
        return payout
