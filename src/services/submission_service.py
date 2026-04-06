from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, or_, select, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.database.models.category import Category
from src.database.models.enums import PayoutStatus, RejectionReason, SubmissionStatus
from src.database.models.publication import Payout, PublicationArchive
from src.database.models.submission import ReviewAction, Submission
from src.database.models.user import User
from src.main_operators import MAIN_OPERATOR_GROUPS, category_title_to_main_group_label
from src.utils.phone_norm import normalize_phone_key, normalize_phone_strict


class SubmissionService:
    """Сервис операций с карточками контента.

    Унифицированный заголовок «Номер — Категория»: `src.utils.submission_format` (`format_submission_title`).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, submission_id: int) -> Submission | None:
        """Возвращает карточку по ID или None."""

        return await self._session.get(Submission, submission_id)

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

    async def get_daily_assets_stats(self, user_id: int) -> dict:
        """Статистика и сумма к выплате строго за сегодняшний день по МСК."""
        from datetime import datetime, timedelta, timezone
        from decimal import Decimal
        from sqlalchemy import select, func, case
        from src.database.models.enums import SubmissionStatus
        from src.database.models.submission import Submission

        msk_tz = timezone(timedelta(hours=3))
        now_msk = datetime.now(msk_tz)
        start_of_day = now_msk.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_day_utc = start_of_day.astimezone(timezone.utc)

        stmt = select(
            func.count(case((Submission.status == SubmissionStatus.PENDING, 1))),
            func.count(case((Submission.status == SubmissionStatus.IN_REVIEW, 1))),
            func.count(case((Submission.status == SubmissionStatus.ACCEPTED, 1))),
            func.count(case((Submission.status.in_([SubmissionStatus.REJECTED, SubmissionStatus.BLOCKED, SubmissionStatus.NOT_A_SCAN]), 1))),
            func.coalesce(
                func.sum(case((Submission.status == SubmissionStatus.ACCEPTED, Submission.fixed_payout_rate))), 
                Decimal("0.00")
            )
        ).where(
            Submission.user_id == user_id,
            Submission.last_status_change >= start_of_day_utc
        )

        result = await self._session.execute(stmt)
        pending, in_review, accepted, rejected, total_earned = result.one()

        return {
            "pending": int(pending or 0),
            "in_review": int(in_review or 0),
            "accepted": int(accepted or 0),
            "rejected": int(rejected or 0),
            "total_earned": Decimal(total_earned or "0.00")
        }


    async def get_best_category_for_user(self, user_id: int) -> int | None:
        """Определяет самую ходовую категорию за последние 7 дней."""
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import select, func, desc
        from src.database.models.enums import SubmissionStatus
        from src.database.models.submission import Submission

        week_ago = datetime.now(timezone.utc) - timedelta(days=7)

        stmt = (
            select(Submission.category_id, func.count(Submission.id).label("cnt"))
            .where(
                Submission.user_id == user_id,
                Submission.status == SubmissionStatus.ACCEPTED,
                Submission.last_status_change >= week_ago
            )
            .group_by(Submission.category_id)
            .order_by(desc("cnt"))
            .limit(1)
        )

        row = (await self._session.execute(stmt)).first()
        return row[0] if row else None

    async def is_duplicate_accepted(self, image_sha256: str) -> bool:
        # Проверка дубликатов отключена по требованию
        return False

    async def create_submission(
        self,
        user_id: int,
        category_id: int,
        telegram_file_id: str,
        file_unique_id: str,
        image_sha256: str,
        description_text: str,
        attachment_type: str = "photo",
        fixed_payout_rate: Decimal = Decimal("0.0"),
    ) -> Submission:
        """Создаёт новую карточку в статусе pending."""
        from datetime import datetime, timezone
        from src.utils.phone_norm import extract_and_normalize_phone

        now = datetime.now(timezone.utc)
        norm = extract_and_normalize_phone(description_text)

        submission = Submission(
            user_id=user_id,
            category_id=category_id,
            telegram_file_id=telegram_file_id,
            file_unique_id=file_unique_id,
            image_sha256=image_sha256,
            description_text=description_text or "",
            attachment_type=attachment_type,
            status=SubmissionStatus.PENDING,
            phone_normalized=norm,
            fixed_payout_rate=fixed_payout_rate,
            is_duplicate=False,
            last_status_change=now,
        )
        self._session.add(submission)
        await self._session.flush()
        return submission
    
    async def create_bulk_submissions(
        self,
        user_id: int,
        category_id: int,
        fixed_payout_rate: Decimal,
        media_items: list[dict[str, str]],
    ) -> list[Submission]:
        """Отказоустойчивое массовое сохранение загруженных материалов."""
        from datetime import datetime, timezone
        from src.utils.phone_norm import extract_and_normalize_phone

        now = datetime.now(timezone.utc)
        submissions = []

        for item in media_items:
            caption = item.get("caption", "")

            # Интеллектуальный поиск номера в описании к файлу
            norm = extract_and_normalize_phone(caption)

            sub = Submission(
                user_id=user_id,
                category_id=category_id,
                telegram_file_id=item["file_id"],
                file_unique_id=item["unique_id"],
                image_sha256="bulk_skip",
                description_text=caption,
                attachment_type=item["type"],
                status=SubmissionStatus.PENDING,
                phone_normalized=norm,
                fixed_payout_rate=fixed_payout_rate,
                is_duplicate=False,
                last_status_change=now,
            )
            submissions.append(sub)

        self._session.add_all(submissions)
        await self._session.flush()
        return submissions

    async def get_user_dashboard_stats(self, user_id: int) -> dict[str, int | Decimal]:
        """Возвращает агрегированную статистику для дашборда пользователя за один запрос."""

        stmt = select(
            func.count(case((Submission.status.in_([SubmissionStatus.PENDING, SubmissionStatus.IN_REVIEW]), 1))),
            func.count(case((Submission.status == SubmissionStatus.ACCEPTED, 1))),
            func.count(case((Submission.status.in_([SubmissionStatus.REJECTED, SubmissionStatus.BLOCKED, SubmissionStatus.NOT_A_SCAN]), 1))),
            func.coalesce(func.sum(case((Submission.status == SubmissionStatus.ACCEPTED, Submission.accepted_amount))), Decimal("0.00"))
        ).where(Submission.user_id == user_id)

        result = await self._session.execute(stmt)
        pending, accepted, rejected, balance = result.one()

        return {
            "pending": int(pending or 0),
            "accepted": int(accepted or 0),
            "rejected": int(rejected or 0),
            "balance": Decimal(balance or "0.00"),
        }

    async def get_user_esim_seller_stats(self, user_id: int) -> dict[str, int | Decimal | dict[str, int]]:
        """Расширенная статистика продавца eSIM за два запроса (агрегация + категории)."""

        stmt = select(
            func.count(case((Submission.status == SubmissionStatus.BLOCKED, 1))),
            func.count(case((Submission.status == SubmissionStatus.NOT_A_SCAN, 1))),
            func.count(case((Submission.status == SubmissionStatus.REJECTED, 1))),
            func.count(case((Submission.status == SubmissionStatus.ACCEPTED, 1))),
            func.coalesce(func.sum(case((Submission.status == SubmissionStatus.ACCEPTED, Submission.accepted_amount))), Decimal("0.00"))
        ).where(Submission.user_id == user_id)

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

        main_result = await self._session.execute(stmt)
        blocked, not_scan, rejected, accepted_total, balance = main_result.one()

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
            "accepted_total": int(accepted_total or 0),
            "blocked": int(blocked or 0),
            "not_a_scan": int(not_scan or 0),
            "rejected_moderation": int(rejected or 0),
            "balance": Decimal(balance or "0.00"),
            "by_main_operator": by_main,
        }

    async def list_pending_submissions(self, limit: int = 10) -> list[Submission]:
        """Возвращает список ожидающих карточек для проверки админом."""

        stmt = (
            select(Submission)
            .options(joinedload(Submission.category), joinedload(Submission.seller))
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
            .options(joinedload(Submission.category), joinedload(Submission.seller))
            .where(
                Submission.user_id == user_id,
                Submission.status == SubmissionStatus.PENDING,
            )
            .order_by(Submission.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def mark_submissions_in_review(self, submissions: list[Submission], admin_id: int) -> list[Submission]:
        """Переводит список материалов в in_review после успешной пересылки. Возвращает фактически переведённые."""

        if not submissions:
            return []

        affected: list[Submission] = []
        for submission in submissions:
            if submission.status != SubmissionStatus.PENDING:
                continue
            old_status = submission.status
            submission.status = SubmissionStatus.IN_REVIEW
            submission.admin_id = admin_id
            submission.assigned_at = datetime.now(timezone.utc)
            submission.last_status_change = datetime.now(timezone.utc)
            self._session.add(
                ReviewAction(
                    submission_id=submission.id,
                    admin_id=admin_id,
                    from_status=old_status,
                    to_status=SubmissionStatus.IN_REVIEW,
                    comment="Взято в работу пачкой после пересылки",
                )
            )
            affected.append(submission)

        return affected

    async def mark_pending_submissions_not_scan(
        self,
        submissions: list[Submission],
        admin_id: int,
        *,
        comment: str = "Массовый перевод из буфера остатка в NOT_A_SCAN",
    ) -> list[Submission]:
        """Массово переводит pending-материалы в NOT_A_SCAN."""

        if not submissions:
            return []

        affected: list[Submission] = []
        now = datetime.now(timezone.utc)
        for submission in submissions:
            if submission.status != SubmissionStatus.PENDING:
                continue
            old_status = submission.status
            submission.status = SubmissionStatus.NOT_A_SCAN
            submission.admin_id = admin_id
            submission.reviewed_at = now
            submission.rejection_reason = RejectionReason.QUALITY
            submission.rejection_comment = comment
            submission.last_status_change = now
            self._session.add(
                ReviewAction(
                    submission_id=submission.id,
                    admin_id=admin_id,
                    from_status=old_status,
                    to_status=SubmissionStatus.NOT_A_SCAN,
                    comment=comment,
                )
            )
            affected.append(submission)

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
        submission.last_status_change = datetime.now(timezone.utc)

        self._session.add(
            ReviewAction(
                submission_id=submission.id,
                admin_id=admin_id,
                from_status=old_status,
                to_status=SubmissionStatus.IN_REVIEW,
                comment="Взято в работу",
            )
        )
        await self._session.refresh(submission)
        return submission

    async def delete_submission_for_seller(self, submission_id: int, user_id: int) -> bool:
        """Удаляет карточку продавца, если статус позволяет удаление из раздела «Материал»."""

        submission = await self._session.get(Submission, submission_id)
        if submission is None or submission.user_id != user_id:
            return False

        allowed_statuses = {
            SubmissionStatus.PENDING,
            SubmissionStatus.REJECTED,
            SubmissionStatus.BLOCKED,
            SubmissionStatus.NOT_A_SCAN,
        }
        if submission.status not in allowed_statuses:
            return False

        await self._session.delete(submission)
        return True

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
        submission.last_status_change = datetime.now(timezone.utc)

        self._session.add(
            ReviewAction(
                submission_id=submission.id,
                admin_id=admin_id,
                from_status=old_status,
                to_status=SubmissionStatus.REJECTED,
                comment=comment or "Отклонено админом",
            )
        )
        await self._session.refresh(submission)
        return submission

    async def list_in_review_stale(self, threshold: datetime) -> list[Submission]:
        """IN_REVIEW с моментом последнего статуса раньше порога (для мониторинга «зависания»)."""

        ref = func.coalesce(Submission.last_status_change, Submission.assigned_at, Submission.created_at)
        stmt = (
            select(Submission)
            .options(
                joinedload(Submission.admin),
            )
            .where(
                Submission.status == SubmissionStatus.IN_REVIEW,
                ref < threshold,
            )
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_in_review_submissions(self, admin_id: int, limit: int = 10) -> list[Submission]:
        """Возвращает карточки в статусе in_review (все карточки для любого админа)."""

        conditions = [Submission.status == SubmissionStatus.IN_REVIEW]

        stmt = (
            select(Submission)
            .options(
                joinedload(Submission.category),
                joinedload(Submission.seller),
            )
            .where(*conditions)
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
        """Возвращает page карточек in_review и общее число карточек.
        Все админы видят все карточки.
        """

        conditions = [Submission.status == SubmissionStatus.IN_REVIEW]
        if seller_id is not None:
            conditions.append(Submission.user_id == seller_id)
        if category_id is not None:
            conditions.append(Submission.category_id == category_id)
        if date_from is not None:
            conditions.append(Submission.created_at >= date_from)

        stmt = (
            select(Submission)
            .options(
                joinedload(Submission.category),
                joinedload(Submission.seller),
            )
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

        digits = "".join(ch for ch in query if ch.isdigit())
        
        if len(digits) == 11:
            where_clause = Submission.phone_normalized == digits

        else:
            where_clause = Submission.phone_normalized.like(f"%{digits}")


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
            .options(
                joinedload(Submission.category),
                joinedload(Submission.seller),
            )
            .join(User, Submission.user_id == User.id)
            .where(*base_conditions)
            .order_by(Submission.created_at.desc())
            .offset(page * page_size)
            .limit(page_size)
        )
        rows = list((await self._session.execute(stmt)).all())
        total_stmt = select(func.count(Submission.id)).where(*base_conditions)
        total = int((await self._session.execute(total_stmt)).scalar_one())
        return rows, total

    async def search_by_phone_partial(
        self,
        query: str,
        limit: int = 5,
    ) -> list[Submission]:
        """Быстрый поиск для inline query: по префиксу номера (только цифры).
        
        Пример: query="234" найдёт +79995555234, +79998765234, и т.д.
        Ищет только ACCEPTED (готовые к продаже).
        """

        # Извлекаем только цифры из запроса
        digits = "".join(ch for ch in query if ch.isdigit())
        if len(digits) < 3:
            return []

        # Ищем товары, где номер содержит эти цифры, и статус ACCEPTED
        stmt = (
            select(Submission)
            .options(
                joinedload(Submission.category),
                joinedload(Submission.seller),
            )
            .where(
                Submission.description_text.like(f"%{digits}%"),
                Submission.status == SubmissionStatus.ACCEPTED,
            )
            .order_by(Submission.created_at.desc())
            .limit(limit)
        )
        results = list((await self._session.execute(stmt)).scalars().all())
        return results

    async def search_by_phone_suffix(
        self,
        digits: str,
        limit: int = 10,
    ) -> list[Submission]:
        """Поиск симок по последним цифрам номера (все статусы).

        Используется в админском «🔍 Поиск симки».
        """

        clean = "".join(ch for ch in digits if ch.isdigit())
        if len(clean) < 3:
            return []

        stmt = (
            select(Submission)
            .options(
                joinedload(Submission.category),
                joinedload(Submission.seller),
            )
            .where(Submission.phone_normalized.like(f"%{clean}"))
            .order_by(Submission.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

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
        submission.last_status_change = datetime.now(timezone.utc)

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
        
        # Группируем выплаты за день: если уже есть PENDING-выплата за этот день и пользователя — увеличиваем сумму и accepted_count
        day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        period_key = day_start.date().isoformat()
        payout = await self._session.execute(
            select(Payout)
            .where(
                Payout.user_id == seller.id,
                Payout.period_key == period_key,
                Payout.status == PayoutStatus.PENDING,
            )
        )
        payout = payout.scalars().first()
        if payout:
            payout.amount = Decimal(payout.amount) + Decimal(category.payout_rate)
            payout.accepted_count += 1
            self._session.add(payout)
        else:
            payout = Payout(
                user_id=seller.id,
                amount=category.payout_rate,
                accepted_count=1,
                period_key=period_key,
                period_date=day_start.date(),
                status=PayoutStatus.PENDING,
                uploaded_count=0,
                blocked_count=0,
                not_a_scan_count=0,
                category_id=category.id,
                unit_price=category.payout_rate,
            )
            self._session.add(payout)

        await self._session.refresh(submission)
        return submission

    _FINAL_REJECT_STATUSES = frozenset(
        {
            SubmissionStatus.REJECTED,
            SubmissionStatus.BLOCKED,
            SubmissionStatus.NOT_A_SCAN,
        }
    )

    async def final_reject_submission(
        self,
        submission_id: int,
        admin_id: int,
        to_status: SubmissionStatus,
        reason: RejectionReason,
        comment: str,
    ) -> Submission | None:
        """Финальное отклонение карточки (незачёт / блок / не скан)."""

        if to_status not in self._FINAL_REJECT_STATUSES:
            return None

        submission = await self._session.get(Submission, submission_id)
        if submission is None or submission.status != SubmissionStatus.IN_REVIEW:
            return None

        old_status = submission.status
        submission.status = to_status
        submission.admin_id = admin_id
        submission.reviewed_at = datetime.now(timezone.utc)
        submission.rejection_reason = reason
        submission.rejection_comment = comment
        submission.last_status_change = datetime.now(timezone.utc)

        self._session.add(
            ReviewAction(
                submission_id=submission.id,
                admin_id=admin_id,
                from_status=old_status,
                to_status=to_status,
                comment=comment,
            )
        )
        await self._session.refresh(submission)
        return submission

    async def final_reject_submissions_batch(
        self,
        *,
        submission_ids: list[int],
        admin_id: int,
        to_status: SubmissionStatus,
        reason: RejectionReason,
        comment: str,
    ) -> list[Submission]:
        """Финально отклоняет список IN_REVIEW карточек одним commit."""

        if to_status not in self._FINAL_REJECT_STATUSES:
            return []
        if not submission_ids:
            return []

        uniq_ids = sorted({int(x) for x in submission_ids if int(x) > 0})
        if not uniq_ids:
            return []

        stmt = (
            select(Submission)
            .where(
                Submission.id.in_(uniq_ids),
                Submission.status == SubmissionStatus.IN_REVIEW,
            )
            .order_by(Submission.id.asc())
        )
        submissions = list((await self._session.execute(stmt)).scalars().all())
        if not submissions:
            return []

        now = datetime.now(timezone.utc)
        for submission in submissions:
            old_status = submission.status
            submission.status = to_status
            submission.admin_id = admin_id
            submission.reviewed_at = now
            submission.rejection_reason = reason
            submission.rejection_comment = comment
            submission.last_status_change = now

            self._session.add(
                ReviewAction(
                    submission_id=submission.id,
                    admin_id=admin_id,
                    from_status=old_status,
                    to_status=to_status,
                    comment=comment,
                )
            )

        return submissions

    async def final_reject_in_review_by_phone(
        self,
        *,
        phone: str,
        admin_id: int | None,
        to_status: SubmissionStatus,
        reason: RejectionReason,
        comment: str,
    ) -> list[Submission]:
        """Финально отклоняет все IN_REVIEW карточки по номеру телефона."""

        if to_status not in self._FINAL_REJECT_STATUSES:
            return []

        normalized = normalize_phone_key(phone)
        if not normalized:
            return []

        plus_variant = f"+{normalized}"
        import re
        # Только если description_text состоит только из цифр, пробелов, +, -, (, )

        def is_pure_number(text):
            # Только цифры и допустимые символы, не более 11 цифр
            digits = re.sub(r"\D", "", text)
            if len(digits) > 11:
                return False
            return bool(re.fullmatch(r"[+\d \-()]{6,24}", text.strip()))

        stmt = (
            select(Submission)
            .where(
                Submission.status == SubmissionStatus.IN_REVIEW,
                or_(
                    Submission.phone_normalized == normalized,
                    (Submission.description_text == normalized) & (is_pure_number(normalized)),
                    (Submission.description_text == plus_variant) & (is_pure_number(plus_variant)),
                ),
            )
            .order_by(Submission.id.asc())
        )
        submissions = list((await self._session.execute(stmt)).scalars().all())
        if not submissions:
            return []

        now = datetime.now(timezone.utc)
        for submission in submissions:
            old_status = submission.status
            submission.status = to_status
            submission.admin_id = admin_id
            submission.reviewed_at = now
            submission.rejection_reason = reason
            submission.rejection_comment = comment
            submission.last_status_change = now

            self._session.add(
                ReviewAction(
                    submission_id=submission.id,
                    admin_id=admin_id,
                    from_status=old_status,
                    to_status=to_status,
                    comment=comment,
                )
            )

        return submissions

    async def final_reject_in_review_by_phone_suffix(
        self,
        *,
        suffix: str,
        admin_id: int | None,
        to_status: SubmissionStatus,
        reason: RejectionReason,
        comment: str,
    ) -> list[Submission]:
        """Финально отклоняет все IN_REVIEW карточки, phone_normalized которых оканчивается на suffix."""

        if to_status not in self._FINAL_REJECT_STATUSES:
            return []
        if not suffix or not suffix.isdigit() or not (4 <= len(suffix) <= 9):
            return []

        stmt = (
            select(Submission)
            .where(
                Submission.status == SubmissionStatus.IN_REVIEW,
                Submission.phone_normalized.like(f"%{suffix}"),
            )
            .order_by(Submission.id.asc())
        )
        submissions = list((await self._session.execute(stmt)).scalars().all())
        if not submissions:
            return []

        now = datetime.now(timezone.utc)
        for submission in submissions:
            old_status = submission.status
            submission.status = to_status
            submission.admin_id = admin_id
            submission.reviewed_at = now
            submission.rejection_reason = reason
            submission.rejection_comment = comment
            submission.last_status_change = now

            self._session.add(
                ReviewAction(
                    submission_id=submission.id,
                    admin_id=admin_id,
                    from_status=old_status,
                    to_status=to_status,
                    comment=comment,
                )
            )

        return submissions

    _DEBIT_WORKED_STATUSES = (
        SubmissionStatus.REJECTED,
        SubmissionStatus.BLOCKED,
        SubmissionStatus.NOT_A_SCAN,
    )

    @staticmethod
    def _utc_day_start() -> datetime:
        now = datetime.now(timezone.utc)
        return now.replace(hour=0, minute=0, second=0, microsecond=0)

    def _worked_filter_conditions(
        self,
        *,
        admin_id: int,
        tab: str,
        seller_id: int | None,
        category_id: int | None,
        date_from: datetime | None,
    ) -> list:
        conds: list = [
            Submission.admin_id == admin_id,
            Submission.reviewed_at.isnot(None),
        ]
        if tab == "credit":
            conds.append(Submission.status == SubmissionStatus.ACCEPTED)
        else:
            conds.append(Submission.status.in_(self._DEBIT_WORKED_STATUSES))
        if seller_id is not None:
            conds.append(Submission.user_id == seller_id)
        if category_id is not None:
            conds.append(Submission.category_id == category_id)
        if date_from is not None:
            conds.append(Submission.reviewed_at >= date_from)
        return conds

    async def get_worked_today_counts(self, admin_id: int) -> tuple[int, int]:
        """Сколько карточек сегодня (UTC) отработано этим админом: зачёт / незачёт."""

        day_start = self._utc_day_start()
        credit_stmt = select(func.count(Submission.id)).where(
            Submission.admin_id == admin_id,
            Submission.reviewed_at >= day_start,
            Submission.status == SubmissionStatus.ACCEPTED,
        )
        debit_stmt = select(func.count(Submission.id)).where(
            Submission.admin_id == admin_id,
            Submission.reviewed_at >= day_start,
            Submission.status.in_(self._DEBIT_WORKED_STATUSES),
        )
        credit = int((await self._session.execute(credit_stmt)).scalar_one())
        debit = int((await self._session.execute(debit_stmt)).scalar_one())
        return credit, debit

    async def get_worked_totals(
        self,
        *,
        admin_id: int,
        tab: str,
        seller_id: int | None,
        category_id: int | None,
        date_from: datetime | None,
    ) -> tuple[int, Decimal]:
        """Количество и сумма USDT (только вкладка «Зачёт») по текущим фильтрам."""

        conds = self._worked_filter_conditions(
            admin_id=admin_id,
            tab=tab,
            seller_id=seller_id,
            category_id=category_id,
            date_from=date_from,
        )
        count_stmt = select(func.count(Submission.id)).where(*conds)
        total = int((await self._session.execute(count_stmt)).scalar_one())
        if tab != "credit":
            return total, Decimal("0.00")
        sum_stmt = select(func.coalesce(func.sum(Submission.accepted_amount), Decimal("0.00"))).where(*conds)
        amount = Decimal((await self._session.execute(sum_stmt)).scalar_one())
        return total, amount

    async def list_worked_submissions_paginated(
        self,
        *,
        admin_id: int,
        page: int,
        page_size: int,
        tab: str,
        seller_id: int | None,
        category_id: int | None,
        date_from: datetime | None,
    ) -> tuple[list[Submission], int]:
        conds = self._worked_filter_conditions(
            admin_id=admin_id,
            tab=tab,
            seller_id=seller_id,
            category_id=category_id,
            date_from=date_from,
        )
        total_stmt = select(func.count(Submission.id)).where(*conds)
        total = int((await self._session.execute(total_stmt)).scalar_one())
        stmt = (
            select(Submission)
            .options(
                joinedload(Submission.category),
                joinedload(Submission.seller),
            )
            .where(*conds)
            .order_by(Submission.reviewed_at.desc().nullslast(), Submission.id.desc())
            .offset(page * page_size)
            .limit(page_size)
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        return rows, total

    async def list_worked_submissions_for_export(
        self,
        *,
        admin_id: int,
        tab: str,
        seller_id: int | None,
        category_id: int | None,
        date_from: datetime | None,
    ) -> list[Submission]:
        conds = self._worked_filter_conditions(
            admin_id=admin_id,
            tab=tab,
            seller_id=seller_id,
            category_id=category_id,
            date_from=date_from,
        )
        stmt = (
            select(Submission)
            .options(
                joinedload(Submission.category),
                joinedload(Submission.seller),
            )
            .where(*conds)
            .order_by(Submission.reviewed_at.desc().nullslast(), Submission.id.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_submission_in_work_for_admin(
        self,
        submission_id: int,
        admin_id: int,
    ) -> Submission | None:
        """Одна карточка «в работе» у админа: без блокировки, только для показа.
        Любой админ может видеть любую карточку в IN_REVIEW статусе.
        """

        conditions = [
            Submission.id == submission_id,
            Submission.status == SubmissionStatus.IN_REVIEW,
        ]

        stmt = (
            select(Submission)
            .options(
                joinedload(Submission.category),
                joinedload(Submission.seller),
            )
            .where(*conditions)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_admin_active_submissions(self, admin_id: int) -> list[Submission]:
        """Возвращает все карточки в работе (все админы видят все карточки)."""

        stmt = (
            select(Submission)
            .options(
                joinedload(Submission.category),
                joinedload(Submission.seller),
                joinedload(Submission.admin),
            )
            .where(Submission.status == SubmissionStatus.IN_REVIEW)
            .order_by(Submission.assigned_at.asc(), Submission.id.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def has_phone_duplicate(self, *, submission_id: int, phone: str | None) -> bool:
        """True, если в БД есть другая заявка с тем же номером."""

        normalized = (phone or "").strip()
        if not normalized:
            return False
        stmt = select(func.count(Submission.id)).where(
            Submission.description_text == normalized,
            Submission.id != submission_id,
        )
        count = int((await self._session.execute(stmt)).scalar_one())
        return count > 0

    async def delete_by_phone_global(self, phone: str) -> int:
        """Удаляет все карточки по номеру телефона из всей БД submissions."""

        normalized = normalize_phone_key(phone)
        if not normalized:
            return 0

        count_stmt = select(func.count(Submission.id)).where(
            or_(
                Submission.phone_normalized == normalized,
                Submission.description_text == normalized,
            )
        )
        total = int((await self._session.execute(count_stmt)).scalar_one())
        if total <= 0:
            return 0

        await self._session.execute(
            delete(Submission).where(
                or_(
                    Submission.phone_normalized == normalized,
                    Submission.description_text == normalized,
                )
            )
        )
        return total

    async def get_user_material_folders(self, user_id: int) -> list[dict[str, Any]]:
        """Папки «Материал»: категории с хотя бы одной карточкой у пользователя."""

        stmt = (
            select(Category.id, Category.title, func.count(Submission.id))
            .join(Submission, Submission.category_id == Category.id)
            .where(Submission.user_id == user_id)
            .group_by(Category.id, Category.title)
            .order_by(Category.title.asc())
        )
        rows = (await self._session.execute(stmt)).all()
        return [{"category_id": int(cid), "title": title, "total": int(cnt)} for cid, title, cnt in rows]

    async def list_user_material_by_category_paginated(
        self,
        *,
        user_id: int,
        category_id: int,
        page: int,
        page_size: int,
        statuses: list[SubmissionStatus] | None,
    ) -> tuple[list[Submission], int]:
        """Карточки пользователя в категории с пагинацией и опциональным фильтром по статусам."""

        conds = [Submission.user_id == user_id, Submission.category_id == category_id]
        if statuses is not None:
            conds.append(Submission.status.in_(statuses))
        total_stmt = select(func.count(Submission.id)).where(*conds)
        total = int((await self._session.execute(total_stmt)).scalar_one())
        stmt = (
            select(Submission)
            .where(*conds)
            .order_by(Submission.created_at.desc(), Submission.id.desc())
            .offset(page * page_size)
            .limit(page_size)
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        return rows, total
