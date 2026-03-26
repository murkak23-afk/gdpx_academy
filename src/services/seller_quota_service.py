from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.seller_daily_quota import SellerDailyQuota


class SellerQuotaService:
    """Ежедневные запросы (квоты) на выгрузку по каждой категории (подтипу оператора)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def today_utc() -> date:
        return datetime.now(timezone.utc).date()

    async def get_quota_for_today(self, user_id: int, category_id: int) -> int:
        """Сколько выгрузок разрешено сегодня (UTC) в этой категории. Без записи — 0."""

        today = self.today_utc()
        stmt = select(SellerDailyQuota.max_uploads).where(
            SellerDailyQuota.user_id == user_id,
            SellerDailyQuota.category_id == category_id,
            SellerDailyQuota.quota_date == today,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return 0
        return max(0, int(row))

    async def upsert_quota(
        self,
        user_id: int,
        category_id: int,
        quota_date: date,
        max_uploads: int,
    ) -> SellerDailyQuota:
        """Задаёт лимит на указанный день (UTC) для пары продавец + категория."""

        stmt = select(SellerDailyQuota).where(
            SellerDailyQuota.user_id == user_id,
            SellerDailyQuota.category_id == category_id,
            SellerDailyQuota.quota_date == quota_date,
        )
        existing = (await self._session.execute(stmt)).scalar_one_or_none()
        if existing is None:
            row = SellerDailyQuota(
                user_id=user_id,
                category_id=category_id,
                quota_date=quota_date,
                max_uploads=max_uploads,
            )
            self._session.add(row)
        else:
            existing.max_uploads = max_uploads
            row = existing
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def list_quotas_for_date(self, quota_date: date) -> list[SellerDailyQuota]:
        stmt = select(SellerDailyQuota).where(SellerDailyQuota.quota_date == quota_date)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
