from sqlalchemy import select, func, case, or_, and_, desc
from src.database.models.submission import Submission
from src.database.models.enums import SubmissionStatus
from src.database.repositories.base import BaseRepository
from datetime import datetime
from typing import Optional, Any

class SubmissionRepository(BaseRepository[Submission]):
    def __init__(self, session):
        super().__init__(model=Submission, session=session)

    async def get_daily_count(self, user_id: int, day_start: datetime) -> int:
        stmt = select(func.count(Submission.id)).where(
            Submission.user_id == user_id,
            Submission.created_at >= day_start
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def get_daily_counts_by_category(self, user_id: int, day_start: datetime) -> dict[int, int]:
        stmt = (
            select(Submission.category_id, func.count(Submission.id))
            .where(Submission.user_id == user_id, Submission.created_at >= day_start)
            .group_by(Submission.category_id)
        )
        result = await self.session.execute(stmt)
        return {int(cid): int(cnt) for cid, cnt in result.all()}

    async def get_stats_for_period(self, user_id: int, start_from: datetime) -> tuple[Any, Any, Any, Any, Any]:
        stmt = select(
            func.count(case((Submission.status == SubmissionStatus.PENDING, 1))),
            func.count(case((Submission.status == SubmissionStatus.IN_REVIEW, 1))),
            func.count(case((Submission.status == SubmissionStatus.ACCEPTED, 1))),
            func.count(case((Submission.status.in_([SubmissionStatus.REJECTED, SubmissionStatus.BLOCKED, SubmissionStatus.NOT_A_SCAN]), 1))),
            func.coalesce(func.sum(case((Submission.status == SubmissionStatus.ACCEPTED, Submission.accepted_amount))), 0)
        ).where(Submission.user_id == user_id, Submission.created_at >= start_from)
        
        result = await self.session.execute(stmt)
        return result.one()

    async def get_best_category_for_user(self, user_id: int, since: datetime) -> int | None:
        stmt = (
            select(Submission.category_id)
            .where(Submission.user_id == user_id, Submission.created_at >= since)
            .group_by(Submission.category_id)
            .order_by(func.count(Submission.id).desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_pending_groups_by_user(self, limit: int = 20) -> list[tuple[int, int]]:
        stmt = (
            select(Submission.user_id, func.count(Submission.id))
            .where(Submission.status == SubmissionStatus.PENDING)
            .group_by(Submission.user_id)
            .order_by(func.max(Submission.created_at).asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [(int(u), int(c)) for u, c in result.all()]

    async def list_pending_submissions_by_user(self, user_id: int) -> list[Submission]:
        from sqlalchemy.orm import joinedload
        stmt = (
            select(Submission)
            .options(joinedload(Submission.category))
            .where(Submission.user_id == user_id, Submission.status == SubmissionStatus.PENDING)
            .order_by(Submission.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_in_review_stale(self, threshold: datetime) -> list[Submission]:
        from sqlalchemy.orm import joinedload
        stmt = (
            select(Submission)
            .options(joinedload(Submission.admin), joinedload(Submission.seller))
            .where(
                Submission.status == SubmissionStatus.IN_REVIEW,
                or_(Submission.assigned_at <= threshold, Submission.updated_at <= threshold)
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_user_material_by_category_paginated(
        self, user_id: int, category_id: int, page: int, page_size: int, statuses: list[SubmissionStatus] | None = None
    ) -> tuple[list[Submission], int]:
        from sqlalchemy.orm import joinedload
        conds = [Submission.user_id == user_id]
        if category_id > 0:
            conds.append(Submission.category_id == category_id)
        if statuses:
            conds.append(Submission.status.in_(statuses))
            
        stmt = (
            select(Submission)
            .options(joinedload(Submission.category))
            .where(*conds)
            .order_by(Submission.created_at.desc())
            .offset(page * page_size)
            .limit(page_size)
        )
        items = list((await self.session.execute(stmt)).scalars().all())
        
        count_stmt = select(func.count(Submission.id)).where(*conds)
        total = await self.session.scalar(count_stmt) or 0
        
        return items, total
