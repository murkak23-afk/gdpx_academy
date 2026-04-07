from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from sqlalchemy import select, func, update, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.models.submission import Submission
from src.database.models.category import Category
from src.database.models.enums import SubmissionStatus

class ModerationService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_pending_paginated(self, page: int, page_size: int = 10) -> tuple[list[Submission], int]:
        """Возвращает страницу ожидающих активов и их общее количество (для Batch-режима)."""
        from sqlalchemy import func
        from sqlalchemy.orm import joinedload
        from src.database.models.user import User
        

        count_stmt = select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING)
        total = (await self._session.execute(count_stmt)).scalar() or 0

        stmt = (
            select(Submission)
            .options(joinedload(Submission.category), joinedload(Submission.seller))
            .where(Submission.status == SubmissionStatus.PENDING)
            .order_by(Submission.category_id.asc(), Submission.created_at.asc())
            .offset(page * page_size)
            .limit(page_size)
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all()), total
    
    async def bulk_finalize_submissions(
        self,
        submission_ids: list[int],
        status: SubmissionStatus,
        admin_id: int,
        reason: str = None,
        comment: str = None
    ) -> int:
        """Транзакционно закрывает пачку заявок с начислением баланса."""
        from src.database.models.user import User
        from src.database.models.submission import ReviewAction

        stmt = select(Submission).where(
            Submission.id.in_(submission_ids),
            Submission.status.in_([SubmissionStatus.PENDING, SubmissionStatus.IN_REVIEW])
        )
        subs = list((await self._session.execute(stmt)).scalars().all())

        if not subs:
            return 0

        now = datetime.now(timezone.utc)
        sellers_credit = {}

        for sub in subs:
            old_status = sub.status
            sub.status = status
            sub.admin_id = admin_id
            sub.reviewed_at = now
            sub.rejection_reason = reason
            sub.rejection_comment = comment

            if status == SubmissionStatus.ACCEPTED:
                sub.accepted_amount = sub.fixed_payout_rate
                sellers_credit[sub.user_id] = sellers_credit.get(sub.user_id, 0) + sub.fixed_payout_rate

            self._session.add(
                ReviewAction(
                    submission_id=sub.id,
                    admin_id=admin_id,
                    from_status=old_status,
                    to_status=status,
                    comment=comment
                )
            )

        if sellers_credit:
            user_stmt = select(User).where(User.id.in_(sellers_credit.keys()))
            users = list((await self._session.execute(user_stmt)).scalars().all())
            for user in users:
                user.pending_balance = (user.pending_balance or 0) + sellers_credit[user.id]

        await self._session.flush()
        return len(subs)

    async def get_queue_stats(self) -> dict:
        """Реальная статистика очереди для дашборда."""
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        total_stmt = select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING)
        total_pending = (await self._session.execute(total_stmt)).scalar() or 0

        in_work_stmt = select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.IN_REVIEW)
        in_work = (await self._session.execute(in_work_stmt)).scalar() or 0

        processed_stmt = select(func.count(Submission.id)).where(
            Submission.status.in_([
                SubmissionStatus.ACCEPTED, SubmissionStatus.REJECTED, 
                SubmissionStatus.BLOCKED, SubmissionStatus.NOT_A_SCAN
            ]),
            Submission.reviewed_at >= today_start
        )
        processed_today = (await self._session.execute(processed_stmt)).scalar() or 0

        return {
            "total_pending": total_pending,
            "in_work": in_work,
            "processed_today": processed_today
        }

    async def get_my_active_paginated(self, admin_id: int, page: int, page_size: int = 10) -> tuple[list[Submission], int]:
        """Возвращает страницу активов В РАБОТЕ у конкретного админа (для Batch-режима)."""
        from sqlalchemy import func
        from sqlalchemy.orm import joinedload
        count_stmt = select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.IN_REVIEW,Submission.admin_id == admin_id
        )
        total = (await self._session.execute(count_stmt)).scalar() or 0

        stmt = (
            select(Submission)
            .options(joinedload(Submission.category), joinedload(Submission.seller))
            .where(
                Submission.status == SubmissionStatus.IN_REVIEW,
                Submission.admin_id == admin_id
            )
            .order_by(Submission.category_id.asc(), Submission.created_at.asc())
            .offset(page * page_size)
            .limit(page_size)
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all()), total



    async def get_pending_queue(self, limit: int = 50) -> List[Submission]:
        """Получает список активов, отсортированных по приоритету."""
        stmt = (
            select(Submission)
            .options(joinedload(Submission.category)) # ФИКС MissingGreenlet
            .join(Category, Submission.category_id == Category.id)
            .where(Submission.status == SubmissionStatus.PENDING)
            .order_by(Category.is_priority.desc(), Submission.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def take_items_to_work(self, admin_id: int, count: int, only_priority: bool = False, user_id: Optional[int] = None) -> int:
        """Бронирует N активов за админом (по внутреннему admin_id)."""
        query = (
            select(Submission.id)
            .join(Category, Submission.category_id == Category.id)
            .where(Submission.status == SubmissionStatus.PENDING)
        )
        if only_priority:
            query = query.where(Category.is_priority == True)
        if user_id:
            query = query.where(Submission.user_id == user_id)
            
        query = query.order_by(Category.is_priority.desc(), Submission.created_at.asc()).limit(count)
        ids_res = await self._session.execute(query)
        target_ids = [r[0] for r in ids_res.all()]
        
        if not target_ids:
            return 0

        stmt = (
            update(Submission)
            .where(Submission.id.in_(target_ids))
            .values(status=SubmissionStatus.IN_REVIEW, admin_id=admin_id)
        )
        await self._session.execute(stmt)
        await self._session.flush()
        return len(target_ids)

    async def get_my_active_items(self, admin_id: int) -> int:
        """Считает количество взятых в работу активов (по внутреннему admin_id)."""
        stmt = select(func.count(Submission.id)).where(
            Submission.status == SubmissionStatus.IN_REVIEW,
            Submission.admin_id == admin_id
        )
        return (await self._session.execute(stmt)).scalar() or 0

    async def get_next_my_item(self, admin_id: int) -> Optional[Submission]:
        """Берет следующую карточку из тех, что уже 'в работе' у админа."""
        stmt = (
            select(Submission)
            .options(joinedload(Submission.category)) # ФИКС MissingGreenlet
            .where(Submission.status == SubmissionStatus.IN_REVIEW, Submission.admin_id == admin_id)
            .order_by(Submission.created_at.asc())
            .limit(1)
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def finalize_submission(self, submission_id: int, status: SubmissionStatus, reason: str = None, comment: str = None) -> bool:
        """Закрывает заявку и начисляет баланс при зачёте."""
        from src.database.models.user import User
        sub = await self._session.get(Submission, submission_id)
        if not sub: return False
        
        sub.status = status
        sub.reviewed_at = datetime.now(timezone.utc)
        sub.rejection_reason = reason
        sub.rejection_comment = comment
        
        if status == SubmissionStatus.ACCEPTED:
            sub.accepted_amount = sub.fixed_payout_rate
            seller = await self._session.get(User, sub.user_id)
            if seller:
                seller.pending_balance = (seller.pending_balance or 0) + sub.fixed_payout_rate
        
        await self._session.flush()
        return True

    async def get_pending_sellers(self) -> List[dict]:
        """Группировка очереди по продавцам."""
        from src.database.models.user import User
        stmt = (
            select(User, func.count(Submission.id), func.min(Submission.created_at))
            .join(Submission, Submission.user_id == User.id)
            .where(Submission.status == SubmissionStatus.PENDING)
            .group_by(User.id).order_by(func.min(Submission.created_at).asc())
        )
        res = await self._session.execute(stmt)
        return [{"user": r[0], "count": r[1], "oldest": r[2]} for r in res.all()]

    async def get_pending_for_seller(self, user_id: int, limit: int = 50) -> List[Submission]:
        """Список PENDING активов конкретного продавца."""
        stmt = (
            select(Submission)
            .options(joinedload(Submission.category)) # ФИКС MissingGreenlet
            .where(Submission.user_id == user_id, Submission.status == SubmissionStatus.PENDING)
            .order_by(Submission.created_at.asc()).limit(limit)
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def search_pending_assets(self, query: str, filter_type: str = "all", limit: int = 50) -> List[Submission]:
        """Интеллектуальный многопоточный поиск по активам."""
        from src.database.models.user import User
        
        stmt = (
            select(Submission)
            .options(joinedload(Submission.category)) # ФИКС MissingGreenlet
            .join(Category, Submission.category_id == Category.id)
            .join(User, Submission.user_id == User.id)
            .where(Submission.status == SubmissionStatus.PENDING)
        )

        q = query.strip()
        or_conditions = []
        
        if q.isdigit():
            or_conditions.append(Submission.id == int(q))
            or_conditions.append(User.telegram_id == int(q))
            or_conditions.append(User.id == int(q))
            or_conditions.append(Submission.phone_normalized.like(f"%{q}"))
            
        if q.startswith("@"):
            or_conditions.append(User.username.ilike(f"%{q[1:]}%"))
        elif not q.isdigit():
            or_conditions.append(User.username.ilike(f"%{q}%"))

        if or_conditions:
            stmt = stmt.where(or_(*or_conditions))

        now = datetime.now(timezone.utc)
        if filter_type == "prio":
            stmt = stmt.where(Category.is_priority == True)
        elif filter_type == "sla8":
            stmt = stmt.where(Submission.created_at <= now - timedelta(minutes=8))
        elif filter_type == "sla15":
            stmt = stmt.where(Submission.created_at <= now - timedelta(minutes=15))

        stmt = stmt.order_by(Submission.created_at.asc()).limit(limit)
        res = await self._session.execute(stmt)
        return list(res.scalars().all())
    
    async def take_specific_items_to_work(self, admin_id: int, item_ids: List[int]) -> int:
        """Хирургическое бронирование конкретных карточек после поиска."""
        if not item_ids:
            return 0
        stmt = (
            update(Submission)
            .where(Submission.id.in_(item_ids), Submission.status == SubmissionStatus.PENDING)
            .values(status=SubmissionStatus.IN_REVIEW, admin_id=admin_id)
        )
        res = await self._session.execute(stmt)
        await self._session.flush()
        return res.rowcount
    
    async def get_admin_daily_stats(self, admin_id: int) -> tuple[int, int]:
        """Возвращает личную статистику модератора за сегодня (зачеты, отказы)."""
        from sqlalchemy import case
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        stmt = (
            select(
                func.sum(case((Submission.status == SubmissionStatus.ACCEPTED, 1), else_=0)),
                func.sum(case((Submission.status.in_([SubmissionStatus.REJECTED, SubmissionStatus.BLOCKED, SubmissionStatus.NOT_A_SCAN]), 1), else_=0))
            )
            .where(
                Submission.admin_id == admin_id,
                Submission.reviewed_at >= today_start
            )
        )
        res = await self._session.execute(stmt)
        row = res.one_or_none()
        if row:
            return int(row[0] or 0), int(row[1] or 0)
        return 0, 0
    
    async def auto_finalize_by_phone(self, phone_query: str, status: SubmissionStatus, reason: str, comment: str, is_partial: bool = False) -> list[Submission]:
        """Автоматическая дефектовка симок (выданных в группы), по полному номеру или суффиксу."""
        from src.database.models.submission import ReviewAction
        
        stmt = select(Submission).where(Submission.status == SubmissionStatus.IN_REVIEW)
        
        if is_partial:
            stmt = stmt.where(Submission.phone_normalized.like(f"%{phone_query}"))
        else:
            stmt = stmt.where(Submission.phone_normalized == phone_query)
            
        subs = list((await self._session.execute(stmt)).scalars().all())
        if not subs:
            return []
            
        now = datetime.now(timezone.utc)
        for sub in subs:
            old_status = sub.status
            sub.status = status
            sub.reviewed_at = now
            sub.rejection_reason = reason
            sub.rejection_comment = comment
            
            self._session.add(
                ReviewAction(
                    submission_id=sub.id,
                    admin_id=None, 
                    from_status=old_status,
                    to_status=status,
                    comment=comment
                )
            )
            
        await self._session.flush()
        return subs
    
    async def undo_submission_action(self, submission_id: int, admin_id: int) -> tuple[bool, str]:
        """
        Откатывает последнее действие модератора, если прошло не более 60 секунд.
        Возвращает (Успех, Сообщение_для_UI).
        """
        from src.database.models.user import User
        from src.database.models.submission import ReviewAction

        sub = await self._session.get(Submission, submission_id)
        if not sub or sub.status == SubmissionStatus.PENDING:
            return False, "Карточка не найдена или уже в очереди."

        if sub.admin_id != admin_id:
            return False, "Вы не можете откатить чужую проверку."

        now = datetime.now(timezone.utc)
        if sub.reviewed_at and (now - sub.reviewed_at).total_seconds() > 60:
            return False, "⏳ Время вышло! Откат возможен только в течение 60 секунд."

        # Ищем последнюю запись в аудите
        action_stmt = (
            select(ReviewAction)
            .where(ReviewAction.submission_id == submission_id)
            .order_by(ReviewAction.created_at.desc())
            .limit(1)
        )
        last_action = (await self._session.execute(action_stmt)).scalar_one_or_none()

        if not last_action:
            return False, "История действий не найдена."

        # Финансовый откат
        if sub.status == SubmissionStatus.ACCEPTED:
            seller = await self._session.get(User, sub.user_id)
        if seller:
            from decimal import Decimal
            seller.pending_balance = (seller.pending_balance or Decimal("0.0")) - (sub.accepted_amount or Decimal("0.0"))
            sub.accepted_amount = None


        # Возвращаем карточку в работу
        sub.status = SubmissionStatus.IN_REVIEW
        sub.reviewed_at = None
        sub.rejection_reason = None
        sub.rejection_comment = None

        # Удаляем запись об ошибочном действии
        await self._session.delete(last_action)
        await self._session.flush()

        return True, "↩️ Действие успешно отменено. Карточка возвращена вам в работу."