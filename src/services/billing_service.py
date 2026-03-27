from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.enums import PayoutStatus, SubmissionStatus
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
                func.coalesce(func.sum(Submission.accepted_amount), Decimal("0.00")).label("to_pay"),
            )
            .where(
                Submission.status == SubmissionStatus.ACCEPTED,
                Submission.reviewed_at >= day_start,
            )
            .group_by(Submission.user_id)
        )
        accepted_rows = (await self._session.execute(accepted_stmt)).all()
        accepted_map: dict[int, tuple[int, Decimal]] = {
            int(row.user_id): (int(row.accepted_count), Decimal(row.to_pay)) for row in accepted_rows
        }

        users_stmt = select(User).where(User.id.in_(accepted_map.keys())).order_by(User.id.asc())
        users = list((await self._session.execute(users_stmt)).scalars().all()) if accepted_map else []

        report_rows: list[dict[str, int | str | Decimal]] = []
        for user in users:
            report_rows.append(
                {
                    "user_id": user.id,
                    "telegram_id": user.telegram_id,
                    "username": f"@{user.username}" if user.username else f"id:{user.telegram_id}",
                    "accepted_count": accepted_map.get(user.id, (0, Decimal("0.00")))[0],
                    "to_pay": accepted_map.get(user.id, (0, Decimal("0.00")))[1],
                }
            )
        return report_rows

    async def mark_user_paid(self, user_id: int, paid_by_admin_id: int) -> Payout | None:
        """Сбрасывает pending_balance и создает запись выплаты."""

        user = await self._session.get(User, user_id)
        if user is None:
            return None

        rows = await self.get_daily_report_rows()
        daily_row = next((r for r in rows if int(r["user_id"]) == user_id), None)
        if daily_row is None:
            return None
        amount = Decimal(daily_row["to_pay"])
        if amount <= Decimal("0.00"):
            return None

        day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        accepted_count = int(daily_row["accepted_count"])

        payout = Payout(
            user_id=user.id,
            amount=amount,
            accepted_count=accepted_count,
            period_key=day_start.date().isoformat(),
            period_date=day_start.date(),
            status=PayoutStatus.PAID,
            uploaded_count=accepted_count,
            blocked_count=0,
            not_a_scan_count=0,
            unit_price=None,
            paid_at=datetime.now(timezone.utc),
            paid_by_admin_id=paid_by_admin_id,
            note="manual_daily_report",
        )
        user.pending_balance = max(Decimal("0.00"), Decimal(user.pending_balance) - amount)
        user.total_paid = Decimal(user.total_paid) + amount

        self._session.add(payout)
        await self._session.commit()
        await self._session.refresh(payout)
        return payout

    async def mark_user_paid_with_crypto(
        self,
        *,
        user_id: int,
        paid_by_admin_id: int,
        crypto_check_id: str,
        crypto_check_url: str,
        note: str | None = None,
    ) -> Payout | None:
        payout = await self.mark_user_paid(user_id=user_id, paid_by_admin_id=paid_by_admin_id)
        if payout is None:
            return None
        payout.crypto_check_id = crypto_check_id
        payout.crypto_check_url = crypto_check_url
        payout.note = note or payout.note
        await self._session.commit()
        await self._session.refresh(payout)
        return payout

    async def cancel_user_payout(
        self,
        *,
        user_id: int,
        cancelled_by_admin_id: int,
        reason: str = "manual_cancel",
    ) -> Payout | None:
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
            period_date=day_start.date(),
            status=PayoutStatus.CANCELLED,
            uploaded_count=accepted_count,
            blocked_count=0,
            not_a_scan_count=0,
            unit_price=None,
            cancelled_at=datetime.now(timezone.utc),
            cancelled_by_admin_id=cancelled_by_admin_id,
            cancel_reason=reason,
            note="moved_to_trash",
        )
        user.pending_balance = Decimal("0.00")
        self._session.add(payout)
        await self._session.commit()
        await self._session.refresh(payout)
        return payout

    async def get_payouts_paginated(
        self,
        *,
        status: PayoutStatus,
        page: int,
        page_size: int,
    ) -> tuple[list[tuple[Payout, User]], int]:
        total_stmt = select(func.count(Payout.id)).where(Payout.status == status)
        total = int((await self._session.execute(total_stmt)).scalar_one())
        if total == 0:
            return [], 0

        stmt = (
            select(Payout, User)
            .join(User, User.id == Payout.user_id)
            .where(Payout.status == status)
            .order_by(desc(Payout.created_at), desc(Payout.id))
            .offset(page * page_size)
            .limit(page_size)
        )
        rows = list((await self._session.execute(stmt)).all())
        return rows, total

    async def get_user_payout_history_paginated(
        self,
        *,
        user_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[Payout], int]:
        total_stmt = select(func.count(Payout.id)).where(Payout.user_id == user_id)
        total = int((await self._session.execute(total_stmt)).scalar_one())
        if total == 0:
            return [], 0
        stmt = (
            select(Payout)
            .where(Payout.user_id == user_id)
            .order_by(desc(Payout.created_at), desc(Payout.id))
            .offset(page * page_size)
            .limit(page_size)
        )
        items = list((await self._session.execute(stmt)).scalars().all())
        return items, total
