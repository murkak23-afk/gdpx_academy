from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.enums import RejectionReason, SubmissionStatus
from src.database.models.publication import PublicationArchive
from src.database.models.category import Category
from src.database.models.submission import ReviewAction, Submission
from src.database.models.user import User
from src.main_operators import MAIN_OPERATOR_GROUPS, category_title_to_main_group_label


class SubmissionService:
    """Сервис операций с карточками контента."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_daily_count(self, user_id: int) -> int:
        """Считает количество материалов пользователя за текущие сутки UTC."""

        now_utc = datetime.now(timezone.utc)
        day_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

        stmt = select(func.count(Submission.id)).where(
            Submission.user_id == user_id,
            Submission.created_at >= day_start,
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def get_daily_counts_by_category_for_user(self, user_id: int) -> dict[int, int]:
        """Сколько материалов создано сегодня (UTC) по каждой category_id."""

        now_utc = datetime.now(timezone.utc)
        day_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

        stmt = (
            select(Submission.category_id, func.count(Submission.id))
            .where(Submission.user_id == user_id, Submission.created_at >= day_start)
            .group_by(Submission.category_id)
        )
        rows = (await self._session.execute(stmt)).all()
        return {int(cid): int(cnt) for cid, cnt in rows}

    async def is_duplicate_accepted(self, image_sha256: str) -> bool:
        """Проверяет, был ли такой хэш ранее принят админом."""

        stmt = select(Submission.id).where(
            Submission.image_sha256 == image_sha256,
            Submission.status == SubmissionStatus.ACCEPTED,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def create_submission(
        self,
        user_id: int,
        category_id: int,
        telegram_file_id: str,
        file_unique_id: str,
        image_sha256: str,
        description_text: str,
        attachment_type: str = "photo",
    ) -> Submission:
        """Создаёт новую карточку в статусе pending."""

        submission = Submission(
            user_id=user_id,
            category_id=category_id,
            telegram_file_id=telegram_file_id,
            file_unique_id=file_unique_id,
            image_sha256=image_sha256,
            description_text=description_text,
            attachment_type=attachment_type,
            status=SubmissionStatus.PENDING,
        )
        self._session.add(submission)
        await self._session.commit()
        await self._session.refresh(submission)
        return submission

    async def get_user_dashboard_stats(self, user_id: int) -> dict[str, int | Decimal]:
        """Возвращает агрегированную статистику для дашборда пользователя."""

        pending_stmt = select(func.count(Submission.id)).where(
            Submission.user_id == user_id,
            Submission.status.in_([SubmissionStatus.PENDING, SubmissionStatus.IN_REVIEW]),
        )
        accepted_stmt = select(func.count(Submission.id)).where(
            Submission.user_id == user_id,
            Submission.status == SubmissionStatus.ACCEPTED,
        )
        rejected_stmt = select(func.count(Submission.id)).where(
            Submission.user_id == user_id,
            or_(
                Submission.status == SubmissionStatus.REJECTED,
                Submission.status == SubmissionStatus.BLOCKED,
                Submission.status == SubmissionStatus.NOT_A_SCAN,
            ),
        )
        balance_stmt = select(func.coalesce(func.sum(Submission.accepted_amount), Decimal("0.00"))).where(
            Submission.user_id == user_id,
            Submission.status == SubmissionStatus.ACCEPTED,
        )

        pending_count = int((await self._session.execute(pending_stmt)).scalar_one())
        accepted_count = int((await self._session.execute(accepted_stmt)).scalar_one())
        rejected_count = int((await self._session.execute(rejected_stmt)).scalar_one())
        current_balance = Decimal((await self._session.execute(balance_stmt)).scalar_one())

        return {
            "pending": pending_count,
            "accepted": accepted_count,
            "rejected": rejected_count,
            "balance": current_balance,
        }

    async def get_user_esim_seller_stats(self, user_id: int) -> dict[str, int | Decimal | dict[str, int]]:
        """Расширенная статистика продавца eSIM: операторы, блоки, не скан, заработок."""

        blocked_stmt = select(func.count(Submission.id)).where(
            Submission.user_id == user_id,
            Submission.status == SubmissionStatus.BLOCKED,
        )
        not_scan_stmt = select(func.count(Submission.id)).where(
            Submission.user_id == user_id,
            Submission.status == SubmissionStatus.NOT_A_SCAN,
        )
        rejected_only_stmt = select(func.count(Submission.id)).where(
            Submission.user_id == user_id,
            Submission.status == SubmissionStatus.REJECTED,
        )
        accepted_stmt = select(func.count(Submission.id)).where(
            Submission.user_id == user_id,
            Submission.status == SubmissionStatus.ACCEPTED,
        )
        balance_stmt = select(func.coalesce(func.sum(Submission.accepted_amount), Decimal("0.00"))).where(
            Submission.user_id == user_id,
            Submission.status == SubmissionStatus.ACCEPTED,
        )

        by_cat_stmt = (
            select(Category.title, func.count(Submission.id))
            .select_from(Submission)
            .join(Category, Submission.category_id == Category.id)
            .where(
                Submission.user_id == user_id,
                Submission.status == SubmissionStatus.ACCEPTED,
            )
            .group_by(Category.id, Category.title)
        )

        blocked = int((await self._session.execute(blocked_stmt)).scalar_one())
        not_scan = int((await self._session.execute(not_scan_stmt)).scalar_one())
        rejected_only = int((await self._session.execute(rejected_only_stmt)).scalar_one())
        accepted_total = int((await self._session.execute(accepted_stmt)).scalar_one())
        balance = Decimal((await self._session.execute(balance_stmt)).scalar_one())

        by_main: dict[str, int] = {label: 0 for label, _ in MAIN_OPERATOR_GROUPS}
        by_main["Другое"] = 0
        rows = (await self._session.execute(by_cat_stmt)).all()
        for title, cnt in rows:
            label = category_title_to_main_group_label(str(title))
            if label is not None:
                by_main[label] += int(cnt)
            else:
                by_main["Другое"] += int(cnt)

        return {
            "accepted_total": accepted_total,
            "blocked": blocked,
            "not_a_scan": not_scan,
            "rejected_moderation": rejected_only,
            "balance": balance,
            "by_main_operator": by_main,
        }

    async def list_pending_submissions(self, limit: int = 10) -> list[Submission]:
        """Возвращает список ожидающих карточек для проверки админом."""

        stmt = (
            select(Submission)
            .where(Submission.status == SubmissionStatus.PENDING)
            .order_by(Submission.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_pending_groups_by_user(self, limit: int = 20) -> list[tuple[int, int]]:
        """Возвращает группы pending-материалов в формате (user_id, count)."""

        stmt = (
            select(Submission.user_id, func.count(Submission.id))
            .where(Submission.status == SubmissionStatus.PENDING)
            .group_by(Submission.user_id)
            .order_by(func.max(Submission.created_at).asc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [(int(user_id), int(total_count)) for user_id, total_count in rows]

    async def list_pending_groups_by_user_paginated(
        self,
        page: int,
        page_size: int,
        seller_id: int | None = None,
        category_id: int | None = None,
        date_from: datetime | None = None,
    ) -> tuple[list[tuple[int, int]], int]:
        """Возвращает page групп pending-материалов и общее число групп."""

        conditions = [Submission.status == SubmissionStatus.PENDING]
        if seller_id is not None:
            conditions.append(Submission.user_id == seller_id)
        if category_id is not None:
            conditions.append(Submission.category_id == category_id)
        if date_from is not None:
            conditions.append(Submission.created_at >= date_from)

        groups_stmt = (
            select(Submission.user_id, func.count(Submission.id))
            .where(*conditions)
            .group_by(Submission.user_id)
            .order_by(func.max(Submission.created_at).asc())
            .offset(page * page_size)
            .limit(page_size)
        )
        groups = (await self._session.execute(groups_stmt)).all()

        count_stmt = select(func.count(func.distinct(Submission.user_id))).where(*conditions)
        total_groups = int((await self._session.execute(count_stmt)).scalar_one())
        return [(int(user_id), int(total_count)) for user_id, total_count in groups], total_groups

    async def list_pending_submissions_by_user(self, user_id: int) -> list[Submission]:
        """Возвращает все pending-материалы конкретного продавца."""

        stmt = (
            select(Submission)
            .where(
                Submission.user_id == user_id,
                Submission.status == SubmissionStatus.PENDING,
            )
            .order_by(Submission.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def mark_submissions_in_review(self, submissions: list[Submission], admin_id: int) -> int:
        """Переводит список материалов в in_review после успешной пересылки."""

        if not submissions:
            return 0

        affected = 0
        for submission in submissions:
            if submission.status != SubmissionStatus.PENDING:
                continue
            old_status = submission.status
            submission.status = SubmissionStatus.IN_REVIEW
            submission.admin_id = admin_id
            submission.assigned_at = datetime.now(timezone.utc)
            self._session.add(
                ReviewAction(
                    submission_id=submission.id,
                    admin_id=admin_id,
                    from_status=old_status,
                    to_status=SubmissionStatus.IN_REVIEW,
                    comment="Взято в работу пачкой после пересылки",
                )
            )
            affected += 1

        await self._session.commit()
        return affected

    async def take_to_work(self, submission_id: int, admin_id: int) -> Submission | None:
        """Берет карточку в работу админом."""

        submission = await self._session.get(Submission, submission_id)
        if submission is None or submission.status != SubmissionStatus.PENDING:
            return None

        old_status = submission.status
        submission.status = SubmissionStatus.IN_REVIEW
        submission.admin_id = admin_id
        submission.assigned_at = datetime.now(timezone.utc)

        self._session.add(
            ReviewAction(
                submission_id=submission.id,
                admin_id=admin_id,
                from_status=old_status,
                to_status=SubmissionStatus.IN_REVIEW,
                comment="Взято в работу",
            )
        )
        await self._session.commit()
        await self._session.refresh(submission)
        return submission

    async def reject_submission(
        self,
        submission_id: int,
        admin_id: int,
        reason: RejectionReason = RejectionReason.OTHER,
        comment: str | None = None,
    ) -> Submission | None:
        """Отклоняет карточку на первичной проверке админом."""

        submission = await self._session.get(Submission, submission_id)
        if submission is None or submission.status not in {SubmissionStatus.PENDING, SubmissionStatus.IN_REVIEW}:
            return None

        old_status = submission.status
        submission.status = SubmissionStatus.REJECTED
        submission.admin_id = admin_id
        submission.rejection_reason = reason
        submission.rejection_comment = comment
        submission.reviewed_at = datetime.now(timezone.utc)

        self._session.add(
            ReviewAction(
                submission_id=submission.id,
                admin_id=admin_id,
                from_status=old_status,
                to_status=SubmissionStatus.REJECTED,
                comment=comment or "Отклонено админом",
            )
        )
        await self._session.commit()
        await self._session.refresh(submission)
        return submission

    async def list_in_review_submissions(self, admin_id: int, limit: int = 10) -> list[Submission]:
        """Возвращает карточки админа в статусе in_review."""

        stmt = (
            select(Submission)
            .where(
                Submission.status == SubmissionStatus.IN_REVIEW,
                Submission.admin_id == admin_id,
            )
            .order_by(Submission.assigned_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_in_review_submissions_paginated(
        self,
        admin_id: int,
        page: int,
        page_size: int,
        seller_id: int | None = None,
        category_id: int | None = None,
        date_from: datetime | None = None,
    ) -> tuple[list[Submission], int]:
        """Возвращает page карточек in_review и общее число карточек."""

        conditions = [
            Submission.status == SubmissionStatus.IN_REVIEW,
            Submission.admin_id == admin_id,
        ]
        if seller_id is not None:
            conditions.append(Submission.user_id == seller_id)
        if category_id is not None:
            conditions.append(Submission.category_id == category_id)
        if date_from is not None:
            conditions.append(Submission.created_at >= date_from)

        stmt = (
            select(Submission)
            .where(*conditions)
            .order_by(Submission.assigned_at.asc())
            .offset(page * page_size)
            .limit(page_size)
        )
        items = list((await self._session.execute(stmt)).scalars().all())
        total = int((await self._session.execute(select(func.count(Submission.id)).where(*conditions))).scalar_one())
        return items, total

    async def search_by_phone_paginated(
        self,
        query: str,
        page: int,
        page_size: int,
    ) -> tuple[list[tuple[Submission, User]], int]:
        """Ищет в работе/истории по телефону c пагинацией."""

        if query.startswith("+7") and len(query) == 12:
            where_clause = Submission.description_text == query
        else:
            digits = "".join(ch for ch in query if ch.isdigit())
            where_clause = Submission.description_text.like(f"%{digits}")

        base_conditions = [
            where_clause,
            Submission.status.in_(
                [
                    SubmissionStatus.IN_REVIEW,
                    SubmissionStatus.ACCEPTED,
                    SubmissionStatus.REJECTED,
                    SubmissionStatus.BLOCKED,
                    SubmissionStatus.NOT_A_SCAN,
                ]
            ),
        ]
        stmt = (
            select(Submission, User)
            .join(User, Submission.user_id == User.id)
            .where(*base_conditions)
            .order_by(Submission.created_at.desc())
            .offset(page * page_size)
            .limit(page_size)
        )
        rows = list((await self._session.execute(stmt)).all())
        total = int((await self._session.execute(select(func.count(Submission.id)).where(*base_conditions))).scalar_one())
        return rows, total

    async def accept_submission(
        self,
        submission_id: int,
        admin_id: int,
        archive_chat_id: int,
        archive_message_id: int,
    ) -> Submission | None:
        """Фиксирует принятие карточки, начисляет баланс и пишет архив."""

        submission = await self._session.get(Submission, submission_id)
        if submission is None or submission.status != SubmissionStatus.IN_REVIEW:
            return None

        category = await self._session.get(Category, submission.category_id)
        seller = await self._session.get(User, submission.user_id)
        if category is None or seller is None:
            return None

        old_status = submission.status
        submission.status = SubmissionStatus.ACCEPTED
        submission.reviewed_at = datetime.now(timezone.utc)
        submission.accepted_amount = category.payout_rate

        seller.pending_balance = Decimal(seller.pending_balance) + Decimal(category.payout_rate)

        self._session.add(
            ReviewAction(
                submission_id=submission.id,
                admin_id=admin_id,
                from_status=old_status,
                to_status=SubmissionStatus.ACCEPTED,
                comment="Принято и зачислено",
            )
        )
        self._session.add(
            PublicationArchive(
                submission_id=submission.id,
                archive_chat_id=archive_chat_id,
                archive_message_id=archive_message_id,
                archived_by_user_id=admin_id,
            )
        )
        await self._session.commit()
        await self._session.refresh(submission)
        return submission

    async def final_reject_submission(
        self,
        submission_id: int,
        admin_id: int,
        to_status: SubmissionStatus,
        reason: RejectionReason,
        comment: str,
    ) -> Submission | None:
        """Финальное отклонение карточки (block/not_a_scan)."""

        if to_status not in {SubmissionStatus.BLOCKED, SubmissionStatus.NOT_A_SCAN}:
            return None

        submission = await self._session.get(Submission, submission_id)
        if submission is None or submission.status != SubmissionStatus.IN_REVIEW:
            return None

        old_status = submission.status
        submission.status = to_status
        submission.reviewed_at = datetime.now(timezone.utc)
        submission.rejection_reason = reason
        submission.rejection_comment = comment

        self._session.add(
            ReviewAction(
                submission_id=submission.id,
                admin_id=admin_id,
                from_status=old_status,
                to_status=to_status,
                comment=comment,
            )
        )
        await self._session.commit()
        await self._session.refresh(submission)
        return submission
