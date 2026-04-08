from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.stats_epoch import get_stats_epoch
from src.database.models.category import Category
from src.database.models.enums import SubmissionStatus
from src.database.models.publication import Payout
from src.database.models.submission import Submission, ReviewAction
from src.database.models.user import User


class AdminStatsService:
    """Агрегаты для раздела «Статистика» админ-панели."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._epoch = get_stats_epoch()

    def _effective_start(self, start: datetime) -> datetime:
        """Returns max(start, epoch) to honour stats reset."""
        if self._epoch is not None and self._epoch > start:
            return self._epoch
        return start

    @staticmethod
    def period_bounds(period: str) -> tuple[datetime, datetime]:
        """UTC: day = с начала суток; week = 7 дней; month = 30 дней."""

        now = datetime.now(timezone.utc)
        end = now
        if period == "day":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            start = now - timedelta(days=7)
        elif period == "month":
            start = now - timedelta(days=30)
        else:
            start = now - timedelta(days=7)
        return start, end

    @staticmethod
    def month_bounds_utc(year: int, month: int) -> tuple[datetime, datetime]:
        """UTC-границы календарного месяца [start, end)."""

        start = datetime(year=year, month=month, day=1, tzinfo=timezone.utc)
        if month == 12:
            end = datetime(year=year + 1, month=1, day=1, tzinfo=timezone.utc)
        else:
            end = datetime(year=year, month=month + 1, day=1, tzinfo=timezone.utc)
        return start, end

    async def get_owner_summary_stats(self) -> dict:
        """Сводная статистика для Командного центра владельца (Максимально оптимизировано)."""
        from sqlalchemy import case
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        # 1. Общий долг (сумма балансов селлеров)
        debt_stmt = select(func.sum(User.pending_balance))
        total_debt = await self._session.scalar(debt_stmt) or Decimal("0.00")

        # 2. Агрегированный запрос по Submission и Payout
        # Считаем всё за один проход по индексам
        stats_stmt = select(
            func.sum(case((Payout.status == "paid", Payout.amount), else_=0)).filter(Payout.created_at >= today_start).label("paid_today"),
            func.count(func.distinct(Submission.admin_id)).filter(Submission.reviewed_at >= today_start).label("active_mods"),
            func.sum(case((Submission.status == SubmissionStatus.ACCEPTED, Submission.accepted_amount), else_=0)).filter(Submission.reviewed_at >= today_start).label("vol_24h"),
            func.count(Submission.id).filter(Submission.status == SubmissionStatus.PENDING).label("pending")
        )
        
        # Поскольку таблицы разные, SQLAlchemy может сделать кросс-джоин, если не указать условия.
        # Поэтому для Payout и Submission лучше оставить два быстрых агрегата.
        
        payout_stats = await self._session.execute(
            select(func.sum(Payout.amount)).where(Payout.status == "paid", Payout.created_at >= today_start)
        )
        paid_today = payout_stats.scalar() or Decimal("0.00")

        sub_stats = await self._session.execute(
            select(
                func.count(func.distinct(Submission.admin_id)).filter(Submission.reviewed_at >= today_start),
                func.sum(case((Submission.status == SubmissionStatus.ACCEPTED, Submission.accepted_amount), else_=0)).filter(Submission.reviewed_at >= today_start),
                func.count(Submission.id).filter(Submission.status == SubmissionStatus.PENDING)
            )
        )
        active_mods, volume_24h, total_pending = sub_stats.one()

        # 3. Топ оператор (оставляем быстрым лимитированным запросом)
        top_op_stmt = (
            select(Category.operator)
            .join(Submission, Submission.category_id == Category.id)
            .where(Submission.reviewed_at >= today_start)
            .group_by(Category.operator)
            .order_by(func.count(Submission.id).desc())
            .limit(1)
        )
        top_operator = await self._session.scalar(top_op_stmt) or "N/A"

        return {
            "total_debt": total_debt,
            "paid_today": paid_today,
            "active_mods": active_mods or 0,
            "total_pending": total_pending or 0,
            "volume_24h": volume_24h or Decimal("0.00"),
            "top_operator": top_operator,
        }

    async def get_platform_stats(self, start: datetime, end: datetime) -> dict:
        """Общая статистика по платформе."""
        effective = self._effective_start(start)
        
        # Кол-во симок
        total_stmt = select(func.count(Submission.id)).where(
            Submission.created_at >= effective,
            Submission.created_at <= end
        )
        total_count = await self._session.scalar(total_stmt) or 0
        
        # Кол-во принятых
        accepted_stmt = select(func.count(Submission.id)).where(
            Submission.status == SubmissionStatus.ACCEPTED,
            Submission.reviewed_at >= effective,
            Submission.reviewed_at <= end
        )
        accepted_count = await self._session.scalar(accepted_stmt) or 0
        
        # Процент брака
        rejected_statuses = [SubmissionStatus.REJECTED, SubmissionStatus.BLOCKED, SubmissionStatus.NOT_A_SCAN]
        rejected_stmt = select(func.count(Submission.id)).where(
            Submission.status.in_(rejected_statuses),
            Submission.reviewed_at >= effective,
            Submission.reviewed_at <= end
        )
        rejected_count = await self._session.scalar(rejected_stmt) or 0
        
        reject_rate = (rejected_count / (accepted_count + rejected_count) * 100) if (accepted_count + rejected_count) > 0 else 0
        
        # Средняя ставка
        avg_rate_stmt = select(func.avg(Submission.accepted_amount)).where(
            Submission.status == SubmissionStatus.ACCEPTED,
            Submission.reviewed_at >= effective,
            Submission.reviewed_at <= end
        )
        avg_rate = await self._session.scalar(avg_rate_stmt) or Decimal("0.00")
        
        return {
            "total_count": total_count,
            "accepted_count": accepted_count,
            "rejected_count": rejected_count,
            "reject_rate": reject_rate,
            "avg_rate": Decimal(avg_rate).quantize(Decimal("0.01")),
        }

    async def get_moderators_performance(self, start: datetime, end: datetime) -> list[dict]:
        """Статистика по модераторам."""
        effective = self._effective_start(start)
        
        stmt = (
            select(
                User.username,
                User.telegram_id,
                func.count(Submission.id).label("total"),
                func.count(Submission.id).filter(Submission.status == SubmissionStatus.ACCEPTED).label("accepted")
            )
            .join(Submission, Submission.admin_id == User.id)
            .where(
                Submission.reviewed_at >= effective,
                Submission.reviewed_at <= end
            )
            .group_by(User.id)
            .order_by(func.count(Submission.id).desc())
        )
        
        rows = (await self._session.execute(stmt)).all()
        return [
            {
                "username": r.username or str(r.telegram_id),
                "total": r.total,
                "accepted": r.accepted,
                "accept_rate": (r.accepted / r.total * 100) if r.total > 0 else 0
            }
            for r in rows
        ]

    async def get_top_sellers_extended(self, start: datetime, end: datetime, limit: int = 10) -> list[dict]:
        """Расширенная статистика по селлерам (топ по объему и качеству)."""
        effective = self._effective_start(start)
        
        stmt = (
            select(
                User.username,
                User.telegram_id,
                func.count(Submission.id).label("total"),
                func.count(Submission.id).filter(Submission.status == SubmissionStatus.ACCEPTED).label("accepted"),
                func.sum(Submission.accepted_amount).label("earned")
            )
            .join(Submission, Submission.user_id == User.id)
            .where(
                Submission.created_at >= effective,
                Submission.created_at <= end
            )
            .group_by(User.id)
            .order_by(func.count(Submission.id).desc())
            .limit(limit)
        )
        
        rows = (await self._session.execute(stmt)).all()
        return [
            {
                "username": r.username or str(r.telegram_id),
                "total": r.total,
                "accepted": r.accepted,
                "quality": (r.accepted / r.total * 100) if r.total > 0 else 0,
                "earned": Decimal(r.earned or 0).quantize(Decimal("0.01"))
            }
            for r in rows
        ]

    async def daily_sim_stats_for_month(self, year: int, month: int) -> list[dict[str, int | date]]:
        """Дневная статистика за месяц по SIM: вход, зачёт и виды брака."""

        start, end = self.month_bounds_utc(year, month)
        effective_start = self._effective_start(start)
        days = (end.date() - start.date()).days

        result: dict[date, dict[str, int | date]] = {}
        for offset in range(days):
            d = start.date() + timedelta(days=offset)
            result[d] = {
                "date": d,
                "incoming": 0,
                "accepted": 0,
                "rejected": 0,
                "blocked": 0,
                "not_a_scan": 0,
            }

        incoming_stmt = (
            select(
                func.date(Submission.created_at).label("d"),
                func.count(Submission.id).label("cnt"),
            )
            .where(
                Submission.created_at >= effective_start,
                Submission.created_at < end,
            )
            .group_by(func.date(Submission.created_at))
        )
        for d, cnt in (await self._session.execute(incoming_stmt)).all():
            if d in result:
                result[d]["incoming"] = int(cnt or 0)

        reviewed_statuses = [
            (SubmissionStatus.ACCEPTED, "accepted"),
            (SubmissionStatus.REJECTED, "rejected"),
            (SubmissionStatus.BLOCKED, "blocked"),
            (SubmissionStatus.NOT_A_SCAN, "not_a_scan"),
        ]
        for status, key in reviewed_statuses:
            stmt = (
                select(
                    func.date(Submission.reviewed_at).label("d"),
                    func.count(Submission.id).label("cnt"),
                )
                .where(
                    Submission.reviewed_at.is_not(None),
                    Submission.reviewed_at >= effective_start,
                    Submission.reviewed_at < end,
                    Submission.status == status,
                )
                .group_by(func.date(Submission.reviewed_at))
            )
            for d, cnt in (await self._session.execute(stmt)).all():
                if d in result:
                    result[d][key] = int(cnt or 0)

        return [result[d] for d in sorted(result.keys())]

    async def count_incoming_submissions(self, start: datetime, end: datetime) -> int:
        effective = self._effective_start(start)
        stmt = select(func.count(Submission.id)).where(
            Submission.created_at >= effective,
            Submission.created_at <= end,
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def count_by_status_reviewed(
        self,
        status: SubmissionStatus,
        start: datetime,
        end: datetime,
    ) -> int:
        effective = self._effective_start(start)
        stmt = select(func.count(Submission.id)).where(
            Submission.status == status,
            Submission.reviewed_at.is_not(None),
            Submission.reviewed_at >= effective,
            Submission.reviewed_at <= end,
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def accepted_by_category(self, start: datetime, end: datetime) -> list[tuple[str, int, Decimal]]:
        effective = self._effective_start(start)
        stmt = (
            select(
                Category.title,
                func.count(Submission.id),
                func.coalesce(func.sum(Submission.accepted_amount), Decimal("0.00")),
            )
            .join(Submission, Submission.category_id == Category.id)
            .where(
                Submission.status == SubmissionStatus.ACCEPTED,
                Submission.reviewed_at.is_not(None),
                Submission.reviewed_at >= effective,
                Submission.reviewed_at <= end,
            )
            .group_by(Category.id, Category.title)
            .order_by(Category.title.asc())
        )
        rows = (await self._session.execute(stmt)).all()
        return [(str(t), int(c), Decimal(a)) for t, c, a in rows]

    async def get_users_paginated(
        self, 
        page: int, 
        page_size: int = 20, 
        role: UserRole | None = None
    ) -> tuple[list[User], int]:
        """Получить список пользователей с пагинацией и фильтром по роли."""
        stmt = select(User)
        if role:
            stmt = stmt.where(User.role == role)
        
        # Считаем общее количество
        count_stmt = select(func.count(User.id))
        if role:
            count_stmt = count_stmt.where(User.role == role)
        total = await self._session.scalar(count_stmt) or 0
        
        # Получаем данные
        stmt = stmt.order_by(User.created_at.desc()).offset(page * page_size).limit(page_size)
        res = await self._session.execute(stmt)
        return res.scalars().all(), total

    async def get_user_detailed_info(self, user_id: int) -> User | None:
        """Получить полную информацию о пользователе по его внутреннему ID."""
        return await self._session.get(User, user_id)

    async def get_online_moderators(self, minutes: int = 30) -> list[dict]:
        """Список модераторов, активных за последние N минут."""
        since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        
        # Получаем последних активных модераторов через ReviewAction
        stmt = (
            select(User.username, User.telegram_id, func.max(ReviewAction.created_at).label("last_act"))
            .join(ReviewAction, ReviewAction.admin_id == User.id)
            .where(ReviewAction.created_at >= since)
            .group_by(User.id)
            .order_by(func.max(ReviewAction.created_at).desc())
        )
        
        rows = (await self._session.execute(stmt)).all()
        return [
            {
                "username": r.username or str(r.telegram_id),
                "last_active": r.last_act
            }
            for r in rows
        ]

    async def get_recent_moderation_actions(self, limit: int = 10) -> list[dict]:
        """Последние N действий модерации для лога в Командном центре."""
        stmt = (
            select(ReviewAction, User.username, Submission.phone_normalized, Submission.id)
            .join(User, ReviewAction.admin_id == User.id)
            .join(Submission, ReviewAction.submission_id == Submission.id)
            .order_by(ReviewAction.created_at.desc())
            .limit(limit)
        )
        
        res = await self._session.execute(stmt)
        out = []
        for action, username, phone, sub_id in res.all():
            out.append({
                "admin": username or "Admin",
                "phone": phone,
                "sub_id": sub_id,
                "to_status": action.to_status,
                "time": action.created_at
            })
        return out

    async def get_avg_accept_amount(self, start: datetime, end: datetime) -> Decimal:
        effective = self._effective_start(start)
        stmt = select(func.avg(Submission.accepted_amount)).where(
            Submission.status == SubmissionStatus.ACCEPTED,
            Submission.reviewed_at.is_not(None),
            Submission.reviewed_at >= effective,
            Submission.reviewed_at <= end,
        )
        val = (await self._session.execute(stmt)).scalar_one_or_none()
        return Decimal(val or 0).quantize(Decimal("0.01"))

    async def top_sellers_by_accept_amount(
        self,
        start: datetime,
        end: datetime,
        *,
        limit: int = 5,
    ) -> list[tuple[str, Decimal, int]]:
        effective = self._effective_start(start)
        stmt = (
            select(
                User.username,
                User.telegram_id,
                func.coalesce(func.sum(Submission.accepted_amount), Decimal("0.00")).label("amt"),
                func.count(Submission.id).label("cnt"),
            )
            .join(Submission, Submission.user_id == User.id)
            .where(
                Submission.status == SubmissionStatus.ACCEPTED,
                Submission.reviewed_at.is_not(None),
                Submission.reviewed_at >= effective,
                Submission.reviewed_at <= end,
            )
            .group_by(User.id, User.username, User.telegram_id)
            .order_by(func.sum(Submission.accepted_amount).desc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        out: list[tuple[str, Decimal, int]] = []
        for username, telegram_id, amt, cnt in rows:
            label = f"@{username}" if username else f"@{telegram_id}"
            out.append((label, Decimal(amt or 0), int(cnt or 0)))
        return out
