from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, delete, desc, func, or_, select, update
from sqlalchemy.orm import joinedload, load_only

from src.database.models.category import Category
from src.database.models.enums import SubmissionStatus, UserRole
from src.database.models.submission import ReviewAction, Submission
from src.database.models.user import User
from src.database.uow import UnitOfWork
# from src.presentation.main_operators import MAIN_OPERATOR_GROUPS, category_title_to_main_group_label
from src.core.cache import cached, invalidate_cache_pattern
from src.core.cache.keyboard_cache import invalidate_kb_cache
from src.core.utils.phone_norm import (
    extract_all_normalized_phones,
    extract_and_normalize_phone,
    normalize_phone_key,
)


class SubmissionService:
    """Сервис операций с карточками контента."""

    def __init__(self, uow: UnitOfWork | AsyncSession | None = None, session: AsyncSession | None = None) -> None:
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.database.uow import UnitOfWork
        
        if session is not None:
            self._uow = UnitOfWork(session)
        elif isinstance(uow, AsyncSession):
            self._uow = UnitOfWork(uow)
        elif uow is not None:
            self._uow = uow
        else:
            raise ValueError("Either uow or session must be provided")

    async def get_by_id(self, submission_id: int) -> Submission | None:
        """Возвращает карточку по ID или None."""
        return await self._uow.submissions.get_by_id(submission_id)

    async def get_daily_count(self, user_id: int) -> int:
        """Считает количество материалов пользователя за текущие сутки UTC."""
        now_utc = datetime.now(timezone.utc)
        day_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        return await self._uow.submissions.get_daily_count(user_id, day_start)

    async def get_daily_counts_by_category_for_user(self, user_id: int) -> dict[int, int]:
        """Сколько материалов создано сегодня (UTC) по каждой category_id."""
        now_utc = datetime.now(timezone.utc)
        day_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        return await self._uow.submissions.get_daily_counts_by_category(user_id, day_start)

    async def get_daily_assets_stats(self, user_id: int) -> dict:
        """Статистика и сумма к выплате строго за сегодняшний день по МСК."""
        msk_tz = timezone(timedelta(hours=3))
        now_msk = datetime.now(msk_tz)
        start_of_day = now_msk.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_day_utc = start_of_day.astimezone(timezone.utc)

        pending, in_review, accepted, rejected, total_earned = await self._uow.submissions.get_stats_for_period(
            user_id, start_of_day_utc
        )

        return {
            "pending": int(pending or 0),
            "in_review": int(in_review or 0),
            "accepted": int(accepted or 0),
            "rejected": int(rejected or 0),
            "total_earned": Decimal(total_earned or "0.00")
        }

    async def get_best_category_for_user(self, user_id: int) -> int | None:
        """Определяет самую ходовую категорию за последние 7 дней."""
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        return await self._uow.submissions.get_best_category_for_user(user_id, week_ago)

    async def is_duplicate_accepted(self, image_sha256: str) -> bool:
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
        sub = await self._uow.submissions.add(submission)
        await invalidate_kb_cache()
        await invalidate_cache_pattern(f"*u_stats*:{user_id}*")
        await invalidate_cache_pattern(f"*u_rank_pos*:{user_id}*")
        await invalidate_cache_pattern("leaderboard:*")
        return sub
    
    async def create_bulk_submissions(
        self,
        user_id: int,
        category_id: int,
        fixed_payout_rate: Decimal,
        media_items: list[dict[str, str]],
    ) -> list[Submission]:
        """Отказоустойчивое массовое сохранение загруженных материалов."""
        now = datetime.now(timezone.utc)
        submissions = []

        for item in media_items:
            caption = item.get("caption", "")
            norms = extract_all_normalized_phones(caption)
            if not norms:
                norms = [None]

            for norm in norms:
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

        for sub in submissions:
            await self._uow.submissions.add(sub)
        await invalidate_kb_cache()
        await invalidate_cache_pattern(f"*u_stats*:{user_id}*")
        await invalidate_cache_pattern(f"*u_rank_pos*:{user_id}*")
        await invalidate_cache_pattern("leaderboard:*")
        return submissions

    # ... Rest of methods using self._uow.session for now to keep it manageable
    # I'll update export_user_submissions_excel to use uow.session
    async def export_user_submissions_excel(self, user_id: int) -> bytes:
        import io
        from openpyxl import Workbook
        
        stmt = (
            select(Submission, Category.title)
            .join(Category, Submission.category_id == Category.id)
            .options(load_only(Submission.id, Submission.created_at, Submission.phone_normalized, Submission.description_text, Submission.status, Submission.accepted_amount))
            .where(Submission.user_id == user_id)
            .order_by(Submission.created_at.desc())
            .limit(500) # Защита от слишком больших выгрузок
        )
        result = await self._uow.session.execute(stmt)
        rows = result.all()

        wb = Workbook()
        ws = wb.active
        ws.title = "GDPX Assets"
        headers = ["ID", "Дата", "Категория", "Телефон", "Статус", "Выплата (USDT)"]
        ws.append(headers)

        for sub, cat_title in rows:
            ws.append([
                sub.id,
                sub.created_at.strftime("%Y-%m-%d %H:%M"),
                cat_title,
                sub.phone_normalized or sub.description_text[:20],
                sub.status.value.upper(),
                float(sub.accepted_amount or 0)
            ])

        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()

    @cached(ttl=60, key_prefix="u_rank_pos")
    async def get_user_rank_position(self, user_id: int) -> tuple[int, int]:
        stmt = (
            select(User.id, func.count(Submission.id).label("cnt"))
            .join(Submission, Submission.user_id == User.id)
            .where(User.role == UserRole.SELLER, Submission.status == SubmissionStatus.ACCEPTED)
            .group_by(User.id)
            .order_by(desc("cnt"))
        )
        result = await self._uow.session.execute(stmt)
        rows = result.all()
        
        total_sellers = len(rows)
        for i, (uid, cnt) in enumerate(rows, 1):
            if uid == user_id:
                return i, total_sellers
        return total_sellers, total_sellers

    @cached(ttl=30, key_prefix="u_stats_detailed")
    async def get_detailed_stats_for_period(self, user_id: int, days: int | None = None) -> dict:
        conds = [Submission.user_id == user_id]
        if days is not None:
            since = datetime.now(timezone.utc) - timedelta(days=days)
            conds.append(Submission.created_at >= since)
            
        stmt = select(
            func.count(case((Submission.status == SubmissionStatus.ACCEPTED, 1))),
            func.count(case((Submission.status == SubmissionStatus.REJECTED, 1))),
            func.count(case((Submission.status == SubmissionStatus.BLOCKED, 1))),
            func.count(case((Submission.status == SubmissionStatus.NOT_A_SCAN, 1))),
            func.coalesce(func.sum(case((Submission.status == SubmissionStatus.ACCEPTED, Submission.accepted_amount))), Decimal("0.00"))
        ).where(*conds)
        
        result = await self._uow.session.execute(stmt)
        accepted, rejected, blocked, not_scan, total_earned = result.one()
        
        total_processed = accepted + rejected + blocked + not_scan
        quality_rate = (accepted / total_processed * 100) if total_processed > 0 else 100.0
        
        return {
            "accepted": int(accepted or 0),
            "rejected": int(rejected or 0),
            "blocked": int(blocked or 0),
            "not_scan": int(not_scan or 0),
            "earned": Decimal(total_earned or "0.00"),
            "quality": float(quality_rate)
        }

    @cached(ttl=30, key_prefix="u_stats_dash")
    async def get_user_dashboard_stats(self, user_id: int) -> dict[str, int | Decimal]:
        stmt = select(
            func.count(case((Submission.status.in_([SubmissionStatus.PENDING, SubmissionStatus.IN_REVIEW]), 1))),
            func.count(case((Submission.status == SubmissionStatus.ACCEPTED, 1))),
            func.count(case((Submission.status.in_([SubmissionStatus.REJECTED, SubmissionStatus.BLOCKED, SubmissionStatus.NOT_A_SCAN]), 1))),
            func.coalesce(func.sum(case((Submission.status == SubmissionStatus.ACCEPTED, Submission.accepted_amount))), Decimal("0.00"))
        ).where(Submission.user_id == user_id, Submission.is_archived.is_(False))

        result = await self._uow.session.execute(stmt)
        pending, accepted, rejected, balance = result.one()

        return {
            "pending": int(pending or 0),
            "accepted": int(accepted or 0),
            "rejected": int(rejected or 0),
            "balance": Decimal(balance or "0.00"),
        }

    @cached(ttl=30, key_prefix="u_stats_seller")
    async def get_user_esim_seller_stats(self, user_id: int) -> dict[str, int | Decimal | dict[str, int]]:
        stmt = select(
            func.count(case((Submission.status == SubmissionStatus.BLOCKED, 1))),
            func.count(case((Submission.status == SubmissionStatus.NOT_A_SCAN, 1))),
            func.count(case((Submission.status == SubmissionStatus.REJECTED, 1))),
            func.count(case((Submission.status == SubmissionStatus.ACCEPTED, 1))),
            func.coalesce(func.sum(case((Submission.status == SubmissionStatus.ACCEPTED, Submission.accepted_amount))), Decimal("0.00"))
        ).where(Submission.user_id == user_id, Submission.is_archived.is_(False))

        by_cat_stmt = (
            select(Category.title, func.count(Submission.id))
            .select_from(Submission)
            .join(Category, Submission.category_id == Category.id)
            .where(
                Submission.user_id == user_id,
                Submission.status == SubmissionStatus.ACCEPTED,
                Submission.is_archived.is_(False)
            )
            .group_by(Category.id, Category.title)
        )

        main_result = await self._uow.session.execute(stmt)
        blocked, not_scan, rejected, accepted_total, balance = main_result.one()

        by_main: dict[str, int] = {label: 0 for label, _ in MAIN_OPERATOR_GROUPS}
        by_main["Другое"] = 0
        rows = (await self._uow.session.execute(by_cat_stmt)).all()
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

    async def archive_daily_submissions(self) -> int:
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(hours=24)
        
        stmt = (
            update(Submission)
            .where(
                Submission.is_archived.is_(False),
                or_(
                    Submission.status == SubmissionStatus.ACCEPTED,
                    and_(
                        Submission.status.in_([
                            SubmissionStatus.BLOCKED, 
                            SubmissionStatus.NOT_A_SCAN, 
                            SubmissionStatus.REJECTED
                        ]),
                        Submission.reviewed_at <= yesterday
                    )
                )
            )
            .values(is_archived=True, archived_at=now)
        )
        result = await self._uow.session.execute(stmt)
        return result.rowcount

    async def auto_transition_issued_to_verification(self, threshold: datetime) -> int:
        """Авто-перевод из IN_WORK в WAIT_CONFIRM (по таймауту 1 час)."""
        now = datetime.now(timezone.utc)
        
        # 1. Находим идентификаторы зависших заявок
        # Используем .value для надежности в сырых фильтрах, если БД капризничает
        stmt = (
            select(Submission.id)
            .where(
                Submission.status == SubmissionStatus.IN_WORK,
                Submission.last_status_change <= threshold
            )
        )
        result = await self._uow.session.execute(stmt)
        ids = [row[0] for row in result.all()]
        
        if not ids:
            return 0
            
        # 2. Обновляем статус в базе одним запросом
        update_stmt = (
            update(Submission)
            .where(Submission.id.in_(ids))
            .values(
                status=SubmissionStatus.WAIT_CONFIRM,
                last_status_change=now
            )
        )
        await self._uow.session.execute(update_stmt)
        
        # 3. Добавляем запись в историю для прозрачности
        actions = [
            ReviewAction(
                submission_id=sid,
                admin_id=None,
                from_status=SubmissionStatus.IN_WORK,
                to_status=SubmissionStatus.WAIT_CONFIRM,
                comment="Автоматический перевод по SLA (зависло >1ч)"
            )
            for sid in ids
        ]
        self._uow.session.add_all(actions)
        
        return len(ids)

    async def delete_submission(self, submission_id: int, user_id: int) -> tuple[bool, str]:
        submission = await self.get_by_id(submission_id)
        if not submission:
            return False, "Актив не найден"
        if submission.user_id != user_id:
            return False, "Это не ваш актив"
        if submission.is_archived:
            return False, "Нельзя отозвать актив из архива"
        if submission.status != SubmissionStatus.PENDING:
            return False, f"Нельзя отозвать актив в статусе {submission.status.value}"
        await self._uow.session.delete(submission)
        await invalidate_kb_cache()
        await invalidate_cache_pattern(f"*u_stats*:{user_id}*")
        await invalidate_cache_pattern(f"*u_rank_pos*:{user_id}*")
        await invalidate_cache_pattern("leaderboard:*")
        return True, "Актив успешно отозван"

    async def list_pending_groups_by_user(self, limit: int = 20) -> list[tuple[int, int]]:
        return list(await self._uow.submissions.list_pending_groups_by_user(limit))

    async def list_pending_groups_by_user_paginated(
        self, page: int, page_size: int, seller_id: int | None = None, category_id: int | None = None, date_from: datetime | None = None,
    ) -> tuple[list[tuple[int, int]], int]:
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
        groups = (await self._uow.session.execute(groups_stmt)).all()
        count_stmt = select(func.count(func.distinct(Submission.user_id))).where(*conditions)
        total_groups = int((await self._uow.session.execute(count_stmt)).scalar_one())
        return [(int(user_id), int(total_count)) for user_id, total_count in groups], total_groups

    async def list_pending_submissions_by_user(self, user_id: int) -> list[Submission]:
        return list(await self._uow.submissions.list_pending_submissions_by_user(user_id))

    async def delete_submission_for_seller(self, submission_id: int, user_id: int) -> bool:
        submission = await self._uow.submissions.get_by_id(submission_id)
        if submission is None or submission.user_id != user_id:
            return False
        allowed_statuses = {
            SubmissionStatus.PENDING, SubmissionStatus.REJECTED, SubmissionStatus.BLOCKED, SubmissionStatus.NOT_A_SCAN,
        }
        if submission.status not in allowed_statuses:
            return False
        await self._uow.session.delete(submission)
        return True

    async def list_in_review_stale(self, threshold: datetime) -> list[Submission]:
        return list(await self._uow.submissions.list_in_review_stale(threshold))

    async def list_in_review_submissions(self, admin_id: int, limit: int = 10) -> list[Submission]:
        conditions = [Submission.status == SubmissionStatus.IN_REVIEW]
        stmt = (
            select(Submission)
            .options(
                joinedload(Submission.category).options(load_only(Category.title)),
                joinedload(Submission.seller).options(load_only(User.username, User.telegram_id)),
                load_only(Submission.id, Submission.telegram_file_id, Submission.assigned_at, Submission.status)
            )
            .where(*conditions)
            .order_by(Submission.assigned_at.asc())
            .limit(limit)
        )
        result = await self._uow.session.execute(stmt)
        return list(result.scalars().all())

    async def list_in_review_submissions_paginated(
        self, admin_id: int, page: int, page_size: int, seller_id: int | None = None, category_id: int | None = None, date_from: datetime | None = None,
    ) -> tuple[list[Submission], int]:
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
                joinedload(Submission.category).options(load_only(Category.title)),
                joinedload(Submission.seller).options(load_only(User.username, User.telegram_id)),
                load_only(Submission.id, Submission.telegram_file_id, Submission.assigned_at, Submission.status)
            )
            .where(*conditions)
            .order_by(Submission.assigned_at.asc())
            .offset(page * page_size)
            .limit(page_size)
        )
        items = list((await self._uow.session.execute(stmt)).scalars().all())
        total = int((await self._uow.session.execute(select(func.count(Submission.id)).where(*conditions))).scalar_one())
        return items, total

    async def search_by_phone_paginated(self, query: str, page: int, page_size: int) -> tuple[list[tuple[Submission, User]], int]:
        digits = "".join(ch for ch in query if ch.isdigit())
        where_clause = Submission.phone_normalized == digits if len(digits) == 11 else Submission.phone_normalized.like(f"%{digits}")
        base_conditions = [where_clause, Submission.status.in_([
            SubmissionStatus.IN_REVIEW, SubmissionStatus.ACCEPTED, SubmissionStatus.REJECTED, SubmissionStatus.BLOCKED, SubmissionStatus.NOT_A_SCAN
        ])]
        stmt = (
            select(Submission, User)
            .options(joinedload(Submission.category), joinedload(Submission.seller))
            .join(User, Submission.user_id == User.id)
            .where(*base_conditions)
            .order_by(Submission.created_at.desc())
            .offset(page * page_size)
            .limit(page_size)
        )
        rows = list((await self._uow.session.execute(stmt)).all())
        total_stmt = select(func.count(Submission.id)).where(*base_conditions)
        total = int((await self._uow.session.execute(total_stmt)).scalar_one())
        return rows, total

    async def search_by_phone_partial(self, query: str, limit: int = 5) -> list[Submission]:
        digits = "".join(ch for ch in query if ch.isdigit())
        if len(digits) < 3: return []
        stmt = (
            select(Submission)
            .options(joinedload(Submission.category), joinedload(Submission.seller))
            .where(Submission.description_text.like(f"%{digits}%"), Submission.status == SubmissionStatus.ACCEPTED)
            .order_by(Submission.created_at.desc())
            .limit(limit)
        )
        return list((await self._uow.session.execute(stmt)).scalars().all())

    async def search_by_phone_suffix(self, digits: str, limit: int = 10) -> list[Submission]:
        clean = "".join(ch for ch in digits if ch.isdigit())
        if len(clean) < 3: return []
        stmt = (
            select(Submission)
            .options(joinedload(Submission.category), joinedload(Submission.seller))
            .where(Submission.phone_normalized.like(f"%{clean}"))
            .order_by(Submission.created_at.desc())
            .limit(limit)
        )
        return list((await self._uow.session.execute(stmt)).scalars().all())

    async def get_worked_today_counts(self, admin_id: int) -> tuple[int, int]:
        day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        credit_stmt = select(func.count(Submission.id)).where(Submission.admin_id == admin_id, Submission.reviewed_at >= day_start, Submission.status == SubmissionStatus.ACCEPTED)
        debit_stmt = select(func.count(Submission.id)).where(Submission.admin_id == admin_id, Submission.reviewed_at >= day_start, Submission.status.in_([SubmissionStatus.REJECTED, SubmissionStatus.BLOCKED, SubmissionStatus.NOT_A_SCAN]))
        credit = int((await self._uow.session.execute(credit_stmt)).scalar_one())
        debit = int((await self._uow.session.execute(debit_stmt)).scalar_one())
        return credit, debit

    async def get_user_material_folders(self, user_id: int, is_archived: bool = False) -> list[dict[str, Any]]:
        msk_tz = timezone(timedelta(hours=3))
        today_start_msk = datetime.now(msk_tz).replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start_msk.astimezone(timezone.utc)
        stmt = select(Category.id, Category.title, func.count(Submission.id)).join(Submission, Submission.category_id == Category.id).where(Submission.user_id == user_id)
        if is_archived: stmt = stmt.where(Submission.created_at < today_start_utc)
        else: stmt = stmt.where(Submission.created_at >= today_start_utc)
        stmt = stmt.group_by(Category.id, Category.title).order_by(Category.title.asc())
        rows = (await self._uow.session.execute(stmt)).all()
        return [{"category_id": int(cid), "title": title, "total": int(cnt)} for cid, title, cnt in rows]

    async def take_from_warehouse(self, category_id: int, count: int) -> list[Submission]:
        """Безопасное извлечение активов со склада (с блокировкой)."""
        # 1. Сначала выбираем только ID с блокировкой FOR UPDATE
        # Это предотвращает конфликт с OUTER JOIN
        id_stmt = (
            select(Submission.id)
            .where(Submission.category_id == category_id, Submission.status == SubmissionStatus.PENDING)
            .order_by(Submission.created_at.asc())
            .limit(count)
            .with_for_update(skip_locked=True)
        )
        id_result = await self._uow.session.execute(id_stmt)
        ids = [row[0] for row in id_result.all()]
        
        if not ids:
            return []

        # 2. Теперь подгружаем полные объекты вместе с селлерами и категориями
        stmt = (
            select(Submission)
            .options(
                joinedload(Submission.seller),
                joinedload(Submission.category)
            )
            .where(Submission.id.in_(ids))
        )
        items = list((await self._uow.session.execute(stmt)).scalars().all())
        
        # 3. Переводим в статус IN_WORK
        now = datetime.now(timezone.utc)
        for item in items:
            item.status = SubmissionStatus.IN_WORK
            item.assigned_at = now
            
        return items

    async def get_warehouse_stats_grouped(self) -> list[dict]:
        stmt = select(Category.id, Category.title, func.count(Submission.id)).join(Submission, Submission.category_id == Category.id).where(Submission.status == SubmissionStatus.PENDING).group_by(Category.id, Category.title).order_by(Category.title.asc())
        rows = (await self._uow.session.execute(stmt)).all()
        return [{"id": int(cid), "title": title, "count": int(cnt)} for cid, title, cnt in rows]

    async def get_category_stock_count(self, category_id: int) -> int:
        stmt = select(func.count(Submission.id)).where(Submission.category_id == category_id, Submission.status == SubmissionStatus.PENDING)
        return int((await self._uow.session.execute(stmt)).scalar_one())

    async def list_user_material_by_category_paginated(
        self, user_id: int, category_id: int, page: int, page_size: int, statuses: list[SubmissionStatus] | None = None
    ) -> tuple[list[Submission], int]:
        return await self._uow.submissions.list_user_material_by_category_paginated(
            user_id, category_id, page, page_size, statuses
        )
