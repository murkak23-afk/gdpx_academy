from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.database.models.publication import PublicationArchive
from src.database.models.submission import Submission
from src.database.models.user import User


class ArchiveService:
    """Сервис архива товаров с хранением 7 дней."""

    RETENTION_DAYS = 7

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def prune_expired(self) -> int:
        """Удаляет архивные записи старше 7 дней."""

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.RETENTION_DAYS)
        stmt = delete(PublicationArchive).where(PublicationArchive.created_at < cutoff)
        result = await self._session.execute(stmt)
        return int(result.rowcount or 0)

    async def search_archive_by_phone(self, query: str, limit: int = 30) -> list[tuple[Submission, User]]:
        """Ищет в архиве по полному номеру или последним цифрам."""

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.RETENTION_DAYS)
        normalized = query.strip()
        if re.fullmatch(r"^\+7\d{10}$", normalized):
            phone_clause = Submission.description_text.like(f"{normalized}%")
        else:
            digits = re.sub(r"\D", "", normalized)
            phone_clause = Submission.description_text.like(f"%{digits}%")

        stmt = (
            select(Submission, User)
            .options(joinedload(Submission.category), joinedload(Submission.seller))
            .join(PublicationArchive, PublicationArchive.submission_id == Submission.id)
            .join(User, Submission.user_id == User.id)
            .where(
                PublicationArchive.created_at >= cutoff,
                phone_clause,
            )
            .order_by(PublicationArchive.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).all())

    async def search_archive_by_phone_paginated(
        self,
        query: str,
        page: int,
        page_size: int,
    ) -> tuple[list[tuple[Submission, User]], int]:
        """Ищет в архиве с пагинацией."""

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.RETENTION_DAYS)
        normalized = query.strip()
        if re.fullmatch(r"^\+7\d{10}$", normalized):
            phone_clause = Submission.description_text.like(f"{normalized}%")
        else:
            digits = re.sub(r"\D", "", normalized)
            phone_clause = Submission.description_text.like(f"%{digits}%")

        conditions = [PublicationArchive.created_at >= cutoff, phone_clause]
        stmt = (
            select(Submission, User)
            .options(joinedload(Submission.category), joinedload(Submission.seller))
            .join(PublicationArchive, PublicationArchive.submission_id == Submission.id)
            .join(User, Submission.user_id == User.id)
            .where(*conditions)
            .order_by(PublicationArchive.created_at.desc())
            .offset(page * page_size)
            .limit(page_size)
        )
        rows = list((await self._session.execute(stmt)).all())
        count_stmt = (
            select(func.count(PublicationArchive.id))
            .join(Submission, PublicationArchive.submission_id == Submission.id)
            .where(*conditions)
        )
        total = int((await self._session.execute(count_stmt)).scalar_one())
        return rows, total
