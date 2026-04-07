from __future__ import annotations
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import select, func, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.user import User
from src.database.models.publication import Payout
from src.database.models.enums import PayoutStatus

class BillingService:
    """Сервис управления финансами, балансами и выплатами."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_sellers_with_balance(self, limit: int = 50, offset: int = 0) -> tuple[List[User], int]:
        """Возвращает список селлеров с положительным балансом и общее их количество."""
        count_stmt = select(func.count(User.id)).where(User.pending_balance > 0)
        total = (await self._session.execute(count_stmt)).scalar() or 0

        stmt = (
            select(User)
            .where(User.pending_balance > 0)
            .order_by(desc(User.pending_balance))
            .offset(offset)
            .limit(limit)
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all()), total

    async def get_seller_balance_info(self, user_id: int) -> User | None:
        """Получает полные финансовые данные конкретного селлера."""
        return await self._session.get(User, user_id)

    async def create_payout_request(self, user_id: int, admin_id: int, amount: Decimal) -> Payout | None:
        """Создает транзакцию выплаты, списывая средства с pending_balance."""
        seller = await self._session.get(User, user_id)
        if not seller or seller.pending_balance < amount or amount <= 0:
            return None

        seller.pending_balance -= amount

        now = datetime.now(timezone.utc)
        period_key = now.strftime("%Y-%W")

        payout = Payout(
            user_id=user_id,
            amount=amount,
            accepted_count=0,
            period_key=period_key,
            status=PayoutStatus.PENDING
        )
        self._session.add(payout)
        await self._session.flush()
        return payout
    
    async def execute_crypto_payout(
        self, 
        user_id: int, 
        admin_id: int, 
        amount: Decimal, 
        check_id: str, 
        check_url: str
    ) -> Payout | None:
        """
        Создает транзакцию выплаты со статусом PAID и безопасно списывает средства.
        """
        seller = await self._session.get(User, user_id)
        if not seller or seller.pending_balance < amount or amount <= 0:
            return None

        # 1. Списываем с баланса ожидания и добавляем в "Всего выплачено"
        seller.pending_balance -= amount
        seller.total_paid = (seller.total_paid or Decimal("0.00")) + amount
        
        # 2. Создаем запись о транзакции
        now = datetime.now(timezone.utc)
        period_key = now.strftime("%Y-%W")
        
        payout = Payout(
            user_id=user_id,
            amount=amount,
            accepted_count=0,
            period_key=period_key,
            status=PayoutStatus.PAID,
            crypto_check_id=check_id,
            crypto_check_url=check_url,
            paid_at=now,
            paid_by_admin_id=admin_id
        )
        self._session.add(payout)
        await self._session.flush()
        
        return payout

    async def get_payout_history(
        self, 
        status: Optional[str] = None, 
        user_id: Optional[int] = None, 
        days: int = 30,
        limit: int = 10,
        offset: int = 0
    ) -> tuple[List[Payout], int]:
        """Возвращает историю выплат с фильтрами."""
        stmt = select(Payout)
        
        if status and status != "all":
            stmt = stmt.where(Payout.status == PayoutStatus(status))
        if user_id:
            stmt = stmt.where(Payout.user_id == user_id)
        
        if days > 0:
            since = datetime.now(timezone.utc) - timedelta(days=days)
            stmt = stmt.where(Payout.created_at >= since)

        # Считаем общее кол-во для пагинации
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self._session.execute(count_stmt)).scalar() or 0

        stmt = stmt.order_by(desc(Payout.created_at)).offset(offset).limit(limit)
        res = await self._session.execute(stmt)
        return list(res.scalars().all()), total

    async def get_payout_by_id(self, payout_id: int) -> Payout | None:
        """Получает детальную информацию о выплате."""
        stmt = select(Payout).where(Payout.id == payout_id)
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def cancel_pending_payout(self, payout_id: int, admin_id: int) -> tuple[bool, str]:
        """Отменяет PENDING выплату и возвращает деньги на баланс селлера."""
        payout = await self.get_payout_by_id(payout_id)
        if not payout:
            return False, "Выплата не найдена."
        
        if payout.status != PayoutStatus.PENDING:
            return False, f"Нельзя отменить выплату в статусе {payout.status.value}."

        seller = await self._session.get(User, payout.user_id)
        if seller:
            seller.pending_balance += payout.amount
        
        payout.status = PayoutStatus.CANCELLED
        payout.cancelled_at = datetime.now(timezone.utc)
        payout.cancelled_by_admin_id = admin_id
        
        await self._session.flush()
        return True, "✅ Выплата отменена. Средства вернулись на баланс селлера."

    async def get_finance_stats(self) -> dict:
        """Собирает статистику по выплатам за периоды."""
        now = datetime.now(timezone.utc)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week = today - timedelta(days=7)
        month = today - timedelta(days=30)

        async def get_period_stats(since: datetime):
            stmt = select(
                func.count(Payout.id),
                func.coalesce(func.sum(Payout.amount), Decimal("0.00"))
            ).where(Payout.status == PayoutStatus.PAID, Payout.paid_at >= since)
            res = (await self._session.execute(stmt)).one()
            return int(res[0] or 0), Decimal(res[1] or 0)

        day_count, day_sum = await get_period_stats(today)
        week_count, week_sum = await get_period_stats(week)
        month_count, month_sum = await get_period_stats(month)

        # Топ-3 селлера по выплатам
        top_stmt = (
            select(User.username, User.telegram_id, func.sum(Payout.amount).label("total"))
            .join(Payout, User.id == Payout.user_id)
            .where(Payout.status == PayoutStatus.PAID)
            .group_by(User.id)
            .order_by(desc("total"))
            .limit(3)
        )
        top_res = await self._session.execute(top_stmt)
        top_sellers = [{"name": r[0] or f"ID:{r[1]}", "amount": Decimal(r[2] or 0)} for r in top_res.all()]

        return {
            "today": {"count": day_count, "sum": day_sum},
            "week": {"count": week_count, "sum": week_sum},
            "month": {"count": month_count, "sum": month_sum},
            "top_sellers": top_sellers
        }
