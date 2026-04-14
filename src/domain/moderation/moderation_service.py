from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

if TYPE_CHECKING:
    from aiogram import Bot
    from src.database.uow import UnitOfWork

from src.database.models.category import Category
from src.database.models.enums import SubmissionStatus
from src.database.models.submission import Submission
from src.database.models.user import User

logger = logging.getLogger(__name__)


class ModerationService:
    """Сервис управления очередью модерации. Оптимизировано для точности статусов."""

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
            
        self._session = self._uow.session  # Легаси-переменная для остальных методов

    async def get_pending_paginated(self, page: int, page_size: int = 10) -> tuple[list[Submission], int]:
        """Возвращает страницу ожидающих активов (не архивных)."""
        count_stmt = select(func.count(Submission.id)).where(
            Submission.status == SubmissionStatus.PENDING, 
            Submission.is_archived == False
        )
        total = (await self._session.execute(count_stmt)).scalar() or 0

        stmt = (
            select(Submission)
            .options(joinedload(Submission.category), joinedload(Submission.seller))
            .where(Submission.status == SubmissionStatus.PENDING, Submission.is_archived == False)
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
        comment: str = None,
        bot: Optional["Bot"] = None,
    ) -> int:
        """Массовая финализация заявок через WorkflowService."""
        from src.domain.submission.workflow_service import WorkflowService
        
        wf_svc = WorkflowService(self._session)
        count = await wf_svc.bulk_transition(
            submission_ids=submission_ids,
            admin_id=admin_id,
            to_status=status,
            rejection_reason=reason,
            comment=comment,
            bot=bot
        )
        if count > 0:
            await self._session.commit()
        return count

    async def finalize_submission(
        self,
        submission_id: int,
        status: SubmissionStatus,
        reason: str | None = None,
        comment: str | None = None,
        bot: Optional["Bot"] = None,
        admin_id: int | None = None,
    ) -> bool:
        """Финальное решение по активу через WorkflowService."""
        from src.domain.submission.workflow_service import WorkflowService
        
        wf_svc = WorkflowService(self._session)
        
        if not admin_id:
            sub = await self._uow.submissions.get_by_id(submission_id)
            admin_id = sub.admin_id if sub else None

        if not admin_id:
            logger.error(f"Cannot finalize #{submission_id} without admin_id")
            return False

        res = await wf_svc.transition(
            submission_id=submission_id,
            admin_id=admin_id,
            to_status=status,
            rejection_reason=reason,
            comment=comment,
            bot=bot
        )
        if res:
            await self._session.commit()
            return True
        return False

    async def auto_finalize_by_phone(
        self, 
        phone_query: str, 
        status: SubmissionStatus, 
        reason: str, 
        comment: str, 
        bot: Optional["Bot"] = None,
        search_status: SubmissionStatus = SubmissionStatus.IN_WORK
    ) -> bool:
        """
        Ищет актив по суффиксу номера в указанном статусе и финализирует его.
        Используется в AUTO-FIX (топики).
        """
        suffix = phone_query[-5:]
        if len(suffix) < 4:
            suffix = phone_query[-4:]

        stmt = (
            select(Submission)
            .options(joinedload(Submission.seller))
            .where(
                Submission.phone_normalized.like(f"%{suffix}"),
                Submission.status == search_status,
                Submission.is_archived == False
            )
            .order_by(Submission.created_at.desc())
            .limit(1)
        )
        res = await self._session.execute(stmt)
        item = res.scalar_one_or_none()

        if not item:
            return False

        return await self.finalize_submission(
            submission_id=item.id,
            status=status,
            reason=reason,
            comment=comment,
            bot=bot,
            admin_id=item.admin_id or 1 # Если админ не назначен, берем системного
        )

    async def get_recent_blocked_grouped(self) -> List[dict]:
        """Возвращает список заблокированных активов за 24ч с группировкой по продавцу и оператору."""
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(hours=24)

        stmt = (
            select(
                User.username,
                Category.title,
                func.count(Submission.id),
                Submission.status
            )
            .join(User, Submission.user_id == User.id)
            .join(Category, Submission.category_id == Category.id)
            .where(
                Submission.status.in_([SubmissionStatus.BLOCKED, SubmissionStatus.NOT_A_SCAN]),
                Submission.reviewed_at >= yesterday,
                Submission.is_archived == False
            )
            .group_by(User.username, Category.title, Submission.status)
            .order_by(User.username.asc(), Category.title.asc())
        )
        res = await self._session.execute(stmt)
        
        # Превращаем в удобный формат
        items = []
        for row in res.all():
            items.append({
                "seller": row[0] or "Unknown",
                "operator": row[1],
                "count": row[2],
                "status": "БЛОК" if row[3] == SubmissionStatus.BLOCKED else "НЕ СКАН"
            })
        return items

    async def get_reform_stats(self) -> dict:
        """Статистика для новой структуры: Склад, Выданные, Проверка, Блокнутые."""
        now = datetime.now(timezone.utc)

        # 1. Склад (PENDING)
        warehouse = await self._session.scalar(
            select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING, Submission.is_archived == False)
        ) or 0

        # 2. Выданные (IN_WORK)
        issued = await self._session.scalar(
            select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.IN_WORK, Submission.is_archived == False)
        ) or 0

        # 3. Проверка (WAIT_CONFIRM + IN_REVIEW)
        verification = await self._session.scalar(
            select(func.count(Submission.id)).where(
                Submission.status.in_([SubmissionStatus.WAIT_CONFIRM, SubmissionStatus.IN_REVIEW]), 
                Submission.is_archived == False
            )
        ) or 0

        # 4. Блокнутые (BLOCKED + NOT_A_SCAN за последние 24 часа)
        yesterday = now - timedelta(hours=24)
        blocked = await self._session.scalar(
            select(func.count(Submission.id)).where(
                Submission.status.in_([SubmissionStatus.BLOCKED, SubmissionStatus.NOT_A_SCAN]),
                Submission.reviewed_at >= yesterday,
                Submission.is_archived == False
            )
        ) or 0

        return {
            "warehouse": warehouse,
            "issued": issued,
            "verification": verification,
            "blocked": blocked
        }

    async def get_queue_stats(self) -> dict:
        """Статистика склада и проверки для дашборда."""
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Склад
        warehouse = await self._session.scalar(
            select(func.count(Submission.id)).where(
                Submission.status == SubmissionStatus.PENDING, 
                Submission.is_archived == False
            )
        ) or 0

        # Проверка
        verification = await self._session.scalar(
            select(func.count(Submission.id)).where(
                Submission.status.in_([SubmissionStatus.WAIT_CONFIRM, SubmissionStatus.IN_REVIEW]), 
                Submission.is_archived == False
            )
        ) or 0

        # Обработано сегодня
        processed_today = await self._session.scalar(
            select(func.count(Submission.id)).where(
                Submission.status.in_([
                    SubmissionStatus.ACCEPTED,
                    SubmissionStatus.REJECTED,
                    SubmissionStatus.BLOCKED,
                    SubmissionStatus.NOT_A_SCAN,
                ]),
                Submission.reviewed_at >= today_start,
                Submission.is_archived == False
            )
        ) or 0

        return {
            "warehouse": warehouse,
            "verification": verification,
            "processed": processed_today
        }

    async def get_waiting_confirmation_items(self, page: int = 0, page_size: int = 10) -> tuple[List[Submission], int]:
        """Активы, которые требуют ручного зачёта, с пагинацией."""
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        
        base_query = (
            select(Submission)
            .where(
                or_(
                    and_(Submission.status == SubmissionStatus.IN_WORK, Submission.assigned_at <= one_hour_ago),
                    Submission.status == SubmissionStatus.WAIT_CONFIRM,
                    Submission.status == SubmissionStatus.IN_REVIEW
                ),
                Submission.is_archived == False
            )
        )

        # Считаем общее количество
        count_stmt = select(func.count()).select_from(base_query.subquery())
        total = await self._session.scalar(count_stmt) or 0

        # Получаем страницу данных
        stmt = (
            base_query
            .options(joinedload(Submission.category), joinedload(Submission.seller))
            .order_by(Submission.assigned_at.asc())
            .offset(page * page_size)
            .limit(page_size)
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all()), total

    async def get_my_active_items(self, admin_id: int) -> int:
        """Считает количество взятых в работу активов."""
        stmt = select(func.count(Submission.id)).where(
            Submission.status == SubmissionStatus.IN_REVIEW, 
            Submission.admin_id == admin_id,
            Submission.is_archived == False
        )
        return (await self._session.execute(stmt)).scalar() or 0

    async def get_next_my_item(self, admin_id: int) -> Optional[Submission]:
        """Возвращает следующий актив из списка 'в работе' для данного админа."""
        stmt = (
            select(Submission)
            .options(joinedload(Submission.category))
            .where(
                Submission.status == SubmissionStatus.IN_REVIEW,
                Submission.admin_id == admin_id,
                Submission.is_archived == False
            )
            .order_by(Submission.assigned_at.asc())
            .limit(1)
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def rotate_item_in_queue(self, item_id: int) -> None:
        """Перемещает актив в конец личной очереди (обновляет assigned_at)."""
        await self._session.execute(
            update(Submission)
            .where(Submission.id == item_id)
            .values(assigned_at=datetime.now(timezone.utc))
        )
        await self._session.flush()

    async def get_pending_sellers(self, status: SubmissionStatus | List[SubmissionStatus] = SubmissionStatus.PENDING) -> List[dict]:
        """Группировка очереди по продавцам (по списку статусов)."""
        if not isinstance(status, list):
            status = [status]
            
        stmt = (
            select(User, func.count(Submission.id), func.min(Submission.created_at))
            .join(Submission, Submission.user_id == User.id)
            .where(Submission.status.in_(status), Submission.is_archived == False)
            .group_by(User.id)
            .order_by(func.min(Submission.created_at).asc())
        )
        res = await self._session.execute(stmt)
        return [{"user_id": r[0].id, "username": r[0].username, "count": r[1], "oldest": r[2]} for r in res.all()]

    async def get_pending_for_seller(self, user_id: int, status: SubmissionStatus | List[SubmissionStatus] = SubmissionStatus.PENDING, limit: int = 50) -> List[Submission]:
        """Список активов конкретного продавца в указанных статусах."""
        if not isinstance(status, list):
            status = [status]
            
        stmt = (
            select(Submission)
            .options(joinedload(Submission.category))
            .where(
                Submission.user_id == user_id, 
                Submission.status.in_(status),
                Submission.is_archived == False
            )
            .order_by(Submission.created_at.asc())
            .limit(limit)
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def search_pending_assets(self, query: str, filter_type: str = "all", limit: int = 50) -> List[Submission]:
        """Интеллектуальный поиск по активам."""
        stmt = (
            select(Submission)
            .options(joinedload(Submission.category), joinedload(Submission.seller))
            .join(Category, Submission.category_id == Category.id)
            .join(User, Submission.user_id == User.id)
            .where(Submission.status == SubmissionStatus.PENDING, Submission.is_archived == False)
        )

        clean_query = query.strip().replace("+", "").replace(" ", "")

        if clean_query:
            if clean_query.isdigit() and 4 <= len(clean_query) <= 6:
                stmt = stmt.where(Submission.phone_normalized.like(f"%{clean_query}"))
            else:
                stmt = stmt.where(
                    or_(
                        Submission.phone_normalized.contains(clean_query),
                        Submission.id.cast(func.text).contains(clean_query),
                        User.username.ilike(f"%{clean_query}%"),
                    )
                )

        now = datetime.now(timezone.utc)
        if filter_type == "prio":
            stmt = stmt.where(Category.is_priority)
        elif filter_type == "sla8":
            stmt = stmt.where(Submission.created_at <= now - timedelta(minutes=8))
        elif filter_type == "sla15":
            stmt = stmt.where(Submission.created_at <= now - timedelta(minutes=15))

        stmt = stmt.order_by(Submission.created_at.desc()).limit(limit)

        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def take_specific_items_to_work(self, admin_id: int, item_ids: List[int]) -> int:
        """Бронирование конкретных карточек (из Склада или Проверки)."""
        if not item_ids:
            return 0
        stmt = (
            update(Submission)
            .where(
                Submission.id.in_(item_ids), 
                Submission.status.in_([SubmissionStatus.PENDING, SubmissionStatus.WAIT_CONFIRM]),
                Submission.is_archived == False
            )
            .values(
                status=SubmissionStatus.IN_REVIEW, 
                admin_id=admin_id,
                assigned_at=datetime.now(timezone.utc),
                last_status_change=datetime.now(timezone.utc)
            )
        )
        res = await self._session.execute(stmt)
        await self._session.flush()
        return res.rowcount

    async def take_items_to_work(self, admin_id: int, limit: int, user_id: int | None = None) -> int:
        """Массовое бронирование карточек (из Склада или Проверки)."""
        # Сначала находим ID подходящих карточек
        stmt = (
            select(Submission.id)
            .where(
                Submission.status.in_([SubmissionStatus.PENDING, SubmissionStatus.WAIT_CONFIRM]),
                Submission.is_archived == False
            )
        )
        if user_id:
            stmt = stmt.where(Submission.user_id == user_id)
        
        stmt = stmt.order_by(Submission.created_at.asc()).limit(limit).with_for_update(skip_locked=True)
        res = await self._session.execute(stmt)
        item_ids = [r[0] for r in res.all()]

        if not item_ids:
            return 0

        # Обновляем их статус
        upd = (
            update(Submission)
            .where(Submission.id.in_(item_ids))
            .values(
                status=SubmissionStatus.IN_REVIEW,
                admin_id=admin_id,
                assigned_at=datetime.now(timezone.utc),
                last_status_change=datetime.now(timezone.utc)
            )
        )
        await self._session.execute(upd)
        await self._session.flush()
        return len(item_ids)

    async def get_pending_for_seller_paginated(
        self, user_id: int, status: List[SubmissionStatus], page: int = 0, page_size: int = 10
    ) -> tuple[List[Submission], int]:
        """Возвращает карточки продавца с пагинацией и общим количеством."""
        base_query = (
            select(Submission)
            .where(
                Submission.user_id == user_id,
                Submission.status.in_(status),
                Submission.is_archived == False
            )
        )

        # Считаем общее количество
        count_stmt = select(func.count()).select_from(base_query.subquery())
        total = await self._session.scalar(count_stmt) or 0

        # Получаем страницу данных
        stmt = (
            base_query
            .options(joinedload(Submission.category))
            .order_by(Submission.created_at.asc())
            .offset(page * page_size)
            .limit(page_size)
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all()), total

    async def get_admin_daily_stats(self, admin_id: int) -> tuple[int, int]:
        """Личная статистика модератора за сегодня."""
        from sqlalchemy import case

        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        stmt = select(
            func.sum(case((Submission.status == SubmissionStatus.ACCEPTED, 1), else_=0)),
            func.sum(
                case(
                    (
                        Submission.status.in_(
                            [SubmissionStatus.REJECTED, SubmissionStatus.BLOCKED, SubmissionStatus.NOT_A_SCAN]
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
        ).where(Submission.admin_id == admin_id, Submission.reviewed_at >= today_start)
        res = await self._session.execute(stmt)
        row = res.one_or_none()
        if row:
            return int(row[0] or 0), int(row[1] or 0)
        return 0, 0

    async def undo_submission_action(self, submission_id: int, admin_id: int) -> tuple[bool, str]:
        """Откат действия модератора через WorkflowService."""
        from decimal import Decimal

        from src.database.models.submission import ReviewAction

        try:
            sub = await self._uow.submissions.get_by_id(submission_id)
            if not sub or sub.status == SubmissionStatus.PENDING:
                return False, "Карточка не найдена или уже в очереди."

            if sub.admin_id != admin_id:
                return False, "Вы не можете откатить чужую проверку."

            now = datetime.now(timezone.utc)
            if sub.reviewed_at and (now - sub.reviewed_at).total_seconds() > 60:
                return False, "⏳ Время вышло! Откат возможен только в течение 60 секунд."

            action_stmt = (
                select(ReviewAction)
                .where(ReviewAction.submission_id == submission_id)
                .order_by(ReviewAction.created_at.desc())
                .limit(1)
            )
            last_action = (await self._session.execute(action_stmt)).scalar_one_or_none()

            if not last_action:
                return False, "История действий не найдена."

            if sub.status == SubmissionStatus.ACCEPTED:
                seller = await self._uow.users.get_by_id(sub.user_id)
                if seller:
                    seller.pending_balance = (seller.pending_balance or Decimal("0.0")) - (
                        sub.accepted_amount or Decimal("0.0")
                    )
                sub.accepted_amount = None

            sub.status = SubmissionStatus.IN_REVIEW
            sub.reviewed_at = None
            sub.rejection_reason = None
            sub.rejection_comment = None

            await self._session.delete(last_action)
            await self._session.commit()

            return True, "↩️ Действие успешно отменено. Карточка возвращена вам в работу."
        except Exception as e:
            await self._session.rollback()
            logger.exception(f"Error in undo_submission_action: {e}")
            return False, "❌ Ошибка при отмене действия."
