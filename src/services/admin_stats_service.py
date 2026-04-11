from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select, case, union_all, or_, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.stats_epoch import get_stats_epoch
from src.database.models.category import Category
from src.database.models.enums import SubmissionStatus, UserRole
from src.database.models.publication import Payout
from src.database.models.submission import Submission, ReviewAction
from src.database.models.user import User


class AdminStatsService:
    """Агрегаты для раздела «Статистика» админ-панели. Оптимизировано для высокой нагрузки."""

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
        """Сводная статистика для Командного центра владельца."""
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        # 1. Общий долг
        debt_stmt = select(func.sum(User.pending_balance))
        total_debt = await self._session.scalar(debt_stmt) or Decimal("0.00")

        # 2. Агрегированные показатели за 24ч
        sub_stats = await self._session.execute(
            select(
                func.count(func.distinct(case(
                    ((Submission.reviewed_at >= today_start) & (Submission.is_archived == False), Submission.admin_id),
                    else_=None
                ))),
                func.sum(case(
                    ((Submission.status == SubmissionStatus.ACCEPTED) & (Submission.reviewed_at >= today_start) & (Submission.is_archived == False), Submission.accepted_amount),
                    else_=0
                )),
                func.count(case(
                    ((Submission.status == SubmissionStatus.PENDING) & (Submission.is_archived == False), Submission.id),
                    else_=None
                ))
            )
        )
        active_mods, volume_24h, warehouse = sub_stats.one()

        # 3. Выплаты сегодня
        paid_today = await self._session.scalar(
            select(func.sum(Payout.amount)).where(Payout.status == "paid", Payout.created_at >= today_start)
        ) or Decimal("0.00")

        # 4. Топ оператор
        top_operator = await self._session.scalar(
            select(Category.operator)
            .join(Submission, Submission.category_id == Category.id)
            .where(Submission.reviewed_at >= today_start, Submission.is_archived == False)
            .group_by(Category.operator)
            .order_by(func.count(Submission.id).desc())
            .limit(1)
        ) or "N/A"

        return {
            "total_debt": total_debt,
            "paid_today": paid_today,
            "active_mods": active_mods or 0,
            "warehouse": warehouse or 0,
            "volume_24h": volume_24h or Decimal("0.00"),
            "top_operator": top_operator,
        }

    async def get_detailed_finance_audit(self) -> dict:
        """Расширенный финансовый аудит для владельца."""
        now = datetime.now(timezone.utc)
        d1, d7, d30 = now - timedelta(days=1), now - timedelta(days=7), now - timedelta(days=30)

        totals = await self._session.execute(select(func.sum(User.pending_balance), func.sum(User.total_paid)))
        debt, paid_all = totals.one()

        payouts = await self._session.execute(
            select(
                func.sum(case((Payout.created_at >= d1, Payout.amount), else_=0)),
                func.sum(case((Payout.created_at >= d7, Payout.amount), else_=0)),
                func.sum(case((Payout.created_at >= d30, Payout.amount), else_=0))
            ).where(Payout.status == "paid")
        )
        p1, p7, p30 = payouts.one()

        vol30 = await self._session.scalar(
            select(func.sum(Submission.accepted_amount))
            .where(Submission.status == SubmissionStatus.ACCEPTED, Submission.reviewed_at >= d30, Submission.is_archived == False)
        )

        return {
            "total_debt": debt or Decimal("0.00"),
            "total_paid_all_time": paid_all or Decimal("0.00"),
            "paid_today": p1 or Decimal("0.00"),
            "paid_week": p7 or Decimal("0.00"),
            "paid_month": p30 or Decimal("0.00"),
            "volume_30d": vol30 or Decimal("0.00"),
        }

    async def get_platform_stats(self, start: datetime, end: datetime) -> dict:
        """Общая статистика по платформе за период."""
        eff = self._effective_start(start)
        
        stmt = select(
            func.count(Submission.id).label("total"),
            func.count(case(((Submission.status == SubmissionStatus.ACCEPTED) & (Submission.reviewed_at.is_not(None)), Submission.id))).label("acc"),
            func.count(case(((Submission.status.in_([SubmissionStatus.REJECTED, SubmissionStatus.BLOCKED, SubmissionStatus.NOT_A_SCAN])) & (Submission.reviewed_at.is_not(None)), Submission.id))).label("rej"),
            func.avg(case(((Submission.status == SubmissionStatus.ACCEPTED), Submission.accepted_amount))).label("avg_rate")
        ).where(Submission.created_at >= eff, Submission.created_at <= end, Submission.is_archived == False)
        
        row = (await self._session.execute(stmt)).one()
        total, accepted, rejected, avg_rate = row
        
        rate = (rejected / (accepted + rejected) * 100) if (accepted + rejected) > 0 else 0
        
        return {
            "total_count": total or 0,
            "accepted_count": accepted or 0,
            "rejected_count": rejected or 0,
            "reject_rate": rate,
            "avg_rate": Decimal(avg_rate or 0).quantize(Decimal("0.01")),
        }

    async def get_moderators_performance(self, start: datetime, end: datetime) -> list[dict]:
        """Статистика по модераторам за период."""
        eff = self._effective_start(start)
        stmt = (
            select(User.username, User.telegram_id, func.count(Submission.id).label("total"), func.count(case(((Submission.status == SubmissionStatus.ACCEPTED), Submission.id))).label("acc"))
            .join(Submission, Submission.admin_id == User.id)
            .where(Submission.reviewed_at >= eff, Submission.reviewed_at <= end, Submission.is_archived == False)
            .group_by(User.id).order_by(desc("total"))
        )
        rows = (await self._session.execute(stmt)).all()
        return [{"username": r.username or str(r.telegram_id), "total": r.total, "accepted": r.acc, "accept_rate": (r.acc / r.total * 100) if r.total > 0 else 0} for r in rows]

    async def daily_sim_stats_for_month(self, year: int, month: int) -> list[dict[str, int | date]]:
        """Дневная статистика за месяц: Оптимизировано за один запрос."""
        start, end = self.month_bounds_utc(year, month)
        eff = self._effective_start(start)
        
        stmt = select(
            func.date(func.coalesce(Submission.reviewed_at, Submission.created_at)).label("d"),
            func.count(case(((Submission.created_at >= eff) & (Submission.created_at < end), Submission.id))).label("inc"),
            func.count(case(((Submission.status == SubmissionStatus.ACCEPTED) & (Submission.reviewed_at >= eff) & (Submission.reviewed_at < end), Submission.id))).label("acc"),
            func.count(case(((Submission.status == SubmissionStatus.REJECTED) & (Submission.reviewed_at >= eff) & (Submission.reviewed_at < end), Submission.id))).label("rej"),
            func.count(case(((Submission.status == SubmissionStatus.BLOCKED) & (Submission.reviewed_at >= eff) & (Submission.reviewed_at < end), Submission.id))).label("blo"),
            func.count(case(((Submission.status == SubmissionStatus.NOT_A_SCAN) & (Submission.reviewed_at >= eff) & (Submission.reviewed_at < end), Submission.id))).label("nos")
        ).where(Submission.is_archived == False, or_(and_(Submission.created_at >= eff, Submission.created_at < end), and_(Submission.reviewed_at >= eff, Submission.reviewed_at < end))
        ).group_by(func.date(func.coalesce(Submission.reviewed_at, Submission.created_at)))

        rows = (await self._session.execute(stmt)).all()
        
        days = (end.date() - start.date()).days
        res: dict[date, dict] = { (start.date() + timedelta(days=i)): {"date": (start.date() + timedelta(days=i)), "incoming": 0, "accepted": 0, "rejected": 0, "blocked": 0, "not_a_scan": 0} for i in range(days) }

        for d, inc, acc, rej, blo, nos in rows:
            if d in res:
                res[d].update({"incoming": inc, "accepted": acc, "rejected": rej, "blocked": blo, "not_a_scan": nos})
        return [res[d] for d in sorted(res.keys())]

    async def get_users_paginated(self, page: int, page_size: int = 20, role: UserRole | None = None) -> tuple[list[User], int]:
        stmt = select(User)
        if role: stmt = stmt.where(User.role == role)
        total = await self._session.scalar(select(func.count(User.id)).where(User.role == role if role else True)) or 0
        res = await self._session.execute(stmt.order_by(User.created_at.desc()).offset(page * page_size).limit(page_size))
        return list(res.scalars().all()), total

    async def get_user_detailed_info(self, user_id: int) -> User | None:
        return await self._session.get(User, user_id)

    async def get_online_moderators(self, minutes: int = 30) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        stmt = select(User.username, User.telegram_id, func.max(ReviewAction.created_at)).join(ReviewAction, ReviewAction.admin_id == User.id).where(ReviewAction.created_at >= since).group_by(User.id)
        rows = (await self._session.execute(stmt)).all()
        return [{"username": r[0] or str(r[1]), "last_active": r[2]} for r in rows]

    async def get_recent_moderation_actions(self, limit: int = 10) -> list[dict]:
        stmt = select(ReviewAction, User.username, Submission.phone_normalized, Submission.id).join(User, ReviewAction.admin_id == User.id).join(Submission, ReviewAction.submission_id == Submission.id).where(Submission.is_archived == False).order_by(desc(ReviewAction.created_at)).limit(limit)
        res = await self._session.execute(stmt)
        return [{"admin": r[1] or "Admin", "phone": r[2], "sub_id": r[3], "to_status": r[0].to_status, "time": r[0].created_at, "comment": r[0].comment} for r in res.all()]

    async def get_user_actions_history(self, user_id: int, limit: int = 20) -> list[dict]:
        """История действий за один запрос через UNION ALL."""
        s1 = select(ReviewAction.created_at.label("t"), ReviewAction.to_status.label("s"), ReviewAction.comment.label("c"), User.username.label("a"), Submission.phone_normalized.label("p"), Submission.id.label("i"), case((True, "MOD")).label("tp")).join(User, ReviewAction.admin_id == User.id).join(Submission, ReviewAction.submission_id == Submission.id).where(ReviewAction.admin_id == user_id, Submission.is_archived == False)
        s2 = select(ReviewAction.created_at.label("t"), ReviewAction.to_status.label("s"), ReviewAction.comment.label("c"), User.username.label("a"), Submission.phone_normalized.label("p"), Submission.id.label("i"), case((True, "SELL")).label("tp")).join(User, ReviewAction.admin_id == User.id).join(Submission, ReviewAction.submission_id == Submission.id).where(Submission.user_id == user_id, Submission.is_archived == False)
        res = await self._session.execute(union_all(s1, s2).order_by(desc("t")).limit(limit))
        return [{"type": r.tp, "admin": r.a or "Admin", "phone": r.p, "sub_id": r.i, "to_status": r.s, "time": r.t, "comment": r.c} for r in res.all()]

    async def get_leaderboard(self, period: str = "all", page: int = 0, page_size: int = 15) -> tuple[list[dict], int]:
        now, d30 = datetime.now(timezone.utc), datetime.now(timezone.utc) - timedelta(days=30)
        hidden = ["push", "fierroIT", "GDPX1", "GDPX0", "dyachx"]
        base_filters = [Submission.status == SubmissionStatus.ACCEPTED, Submission.is_archived == False, ~User.username.in_(hidden), ~User.pseudonym.in_(hidden), ~User.nickname.in_(hidden)]
        if period == "30d": base_filters.append(Submission.reviewed_at >= d30)
        total = await self._session.scalar(select(func.count(func.distinct(User.id))).join(Submission, Submission.user_id == User.id).where(*base_filters)) or 0
        stmt = select(User.username, User.nickname, User.pseudonym, User.telegram_id, func.sum(Submission.accepted_amount).label("e"), func.count(Submission.id).label("c")
        ).join(Submission, Submission.user_id == User.id).where(*base_filters).group_by(User.id).order_by(desc(period == "30d" and "e" or User.total_paid)).offset(page * page_size).limit(page_size)
        rows = (await self._session.execute(stmt)).all()
        return [{"name": r.nickname or r.pseudonym or r.username or f"ID:*{str(r.telegram_id)[-4:]}", "earned": Decimal(r.e or 0).quantize(Decimal("0.01")), "count": r.c} for r in rows], total

    async def get_user_archive_stats(self, user_id: int, start_date: datetime | None = None) -> dict:
        """Статистика архива пользователя за указанный период (включая всё до 'сегодня')."""
        msk_tz = timezone(timedelta(hours=3))
        today_start_msk = datetime.now(msk_tz).replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start_msk.astimezone(timezone.utc)
        conds = [Submission.user_id == user_id, Submission.created_at < today_start_utc]
        if start_date: conds.append(Submission.created_at >= start_date)
        stmt = select(
            func.count(case((Submission.status == SubmissionStatus.ACCEPTED, 1))).label("acc"),
            func.count(case((Submission.status == SubmissionStatus.REJECTED, 1))).label("rej"),
            func.count(case((Submission.status == SubmissionStatus.BLOCKED, 1))).label("blo"),
            func.count(case((Submission.status == SubmissionStatus.NOT_A_SCAN, 1))).label("nos"),
            func.coalesce(func.sum(case((Submission.status == SubmissionStatus.ACCEPTED, Submission.accepted_amount))), Decimal("0.00")).label("val"),
            func.avg(case((Submission.status == SubmissionStatus.ACCEPTED, Submission.fixed_payout_rate))).label("avg")
        ).where(*conds)
        res = await self._session.execute(stmt)
        acc, rej, blo, nos, val, avg = res.one()
        by_cat_stmt = select(Category.title, func.count(Submission.id)).join(Category, Submission.category_id == Category.id).where(*conds).group_by(Category.title).order_by(Category.title.asc())
        cat_rows = (await self._session.execute(by_cat_stmt)).all()
        return {
            "accepted": int(acc or 0), "rejected": int(rej or 0), "blocked": int(blo or 0), "not_a_scan": int(nos or 0),
            "total_value": Decimal(val or "0.00"), "avg_rate": Decimal(avg or "0.00").quantize(Decimal("0.01")),
            "clusters": [{"title": r[0], "count": r[1]} for r in cat_rows]
        }
