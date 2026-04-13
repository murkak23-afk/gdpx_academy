from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import and_, case, delete, desc, func, or_, select, update
from sqlalchemy.orm import joinedload

from src.database.models.category import Category
from src.database.models.enums import SubmissionStatus
from src.database.models.submission import Submission
from src.database.models.user import User
from src.database.repositories.base import BaseRepository


class SubmissionRepository(BaseRepository[Submission]):
    def __init__(self, session):
        super().__init__(Submission, session)

    async def get_daily_count(self, user_id: int, day_start: datetime) -> int:
        stmt = select(func.count(self.model.id)).where(
            self.model.user_id == user_id,
            self.model.created_at >= day_start,
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def get_daily_counts_by_category(self, user_id: int, day_start: datetime) -> dict[int, int]:
        stmt = (
            select(self.model.category_id, func.count(self.model.id))
            .where(self.model.user_id == user_id, self.model.created_at >= day_start)
            .group_by(self.model.category_id)
        )
        rows = (await self.session.execute(stmt)).all()
        return {int(cid): int(cnt) for cid, cnt in rows}

    async def get_stats_for_period(self, user_id: int, start_time: datetime) -> tuple:
        stmt = select(
            func.count(case((self.model.status == SubmissionStatus.PENDING, 1))),
            func.count(case((self.model.status == SubmissionStatus.IN_REVIEW, 1))),
            func.count(case((self.model.status == SubmissionStatus.ACCEPTED, 1))),
            func.count(case((self.model.status.in_([SubmissionStatus.REJECTED, SubmissionStatus.BLOCKED, SubmissionStatus.NOT_A_SCAN]), 1))),
            func.coalesce(
                func.sum(case((self.model.status == SubmissionStatus.ACCEPTED, self.model.fixed_payout_rate))), 
                Decimal("0.00")
            )
        ).where(
            self.model.user_id == user_id,
            self.model.last_status_change >= start_time
        )
        result = await self.session.execute(stmt)
        return result.one()

    async def get_best_category_for_user(self, user_id: int, week_ago: datetime) -> int | None:
        stmt = (
            select(self.model.category_id, func.count(self.model.id).label("cnt"))
            .where(
                self.model.user_id == user_id,
                self.model.status == SubmissionStatus.ACCEPTED,
                self.model.last_status_change >= week_ago
            )
            .group_by(self.model.category_id)
            .order_by(desc("cnt"))
            .limit(1)
        )
        row = (await self.session.execute(stmt)).first()
        return row[0] if row else None

    async def list_pending_groups_by_user(self, limit: int) -> Sequence[tuple[int, int]]:
        stmt = (
            select(self.model.user_id, func.count(self.model.id))
            .where(self.model.status == SubmissionStatus.PENDING)
            .group_by(self.model.user_id)
            .order_by(func.max(self.model.created_at).asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.all()

    async def list_pending_submissions_by_user(self, user_id: int) -> Sequence[Submission]:
        stmt = (
            select(self.model)
            .options(joinedload(self.model.category), joinedload(self.model.seller))
            .where(
                self.model.user_id == user_id,
                self.model.status == SubmissionStatus.PENDING,
            )
            .order_by(self.model.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_in_review_stale(self, threshold: datetime) -> Sequence[Submission]:
        ref = func.coalesce(self.model.last_status_change, self.model.assigned_at, self.model.created_at)
        stmt = (
            select(self.model)
            .options(joinedload(self.model.admin))
            .where(
                self.model.status == SubmissionStatus.IN_REVIEW,
                ref < threshold,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
