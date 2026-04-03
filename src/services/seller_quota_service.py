from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

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
        """
        Сколько выгрузок разрешено сегодня (UTC) в этой категории.

        Логика:
        - если есть запись в `seller_daily_quotas` (старый сценарий) — используем её;
        - иначе берём лимит из `categories.total_upload_limit`, который админ задаёт через `/adm_oper`.
        """

        # Лимит по количеству загрузок отключён по требованию
        return 10**9

    async def upsert_quota(
        self,
        user_id: int,
        category_id: int,
        quota_date: date,
        max_uploads: int,
        unit_price: Decimal,
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
                unit_price=unit_price,
            )
            self._session.add(row)
        else:
            existing.max_uploads = max_uploads
            existing.unit_price = unit_price
            row = existing
        await self._session.refresh(row)
        return row

    async def list_quotas_for_date(self, quota_date: date) -> list[SellerDailyQuota]:
        stmt = select(SellerDailyQuota).where(SellerDailyQuota.quota_date == quota_date)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_unit_price_for_date(self, user_id: int, category_id: int, quota_date: date) -> Decimal:
        stmt = select(SellerDailyQuota.unit_price).where(
            SellerDailyQuota.user_id == user_id,
            SellerDailyQuota.category_id == category_id,
            SellerDailyQuota.quota_date == quota_date,
        )
        value = (await self._session.execute(stmt)).scalar_one_or_none()
        if value is None:
            return Decimal("0.00")
        return Decimal(value)

    async def delete_quota_for_date(self, user_id: int, category_id: int, quota_date: date) -> bool:
        stmt = select(SellerDailyQuota).where(
            SellerDailyQuota.user_id == user_id,
            SellerDailyQuota.category_id == category_id,
            SellerDailyQuota.quota_date == quota_date,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return False
        await self._session.delete(row)
        return True

    async def clear_quotas_for_date(self, quota_date: date) -> int:
        rows = await self.list_quotas_for_date(quota_date)
        if not rows:
            return 0
        for row in rows:
            await self._session.delete(row)
        return len(rows)

    async def clear_quotas_for_category_on_date(self, category_id: int, quota_date: date) -> int:
        stmt = select(SellerDailyQuota).where(
            SellerDailyQuota.category_id == category_id,
            SellerDailyQuota.quota_date == quota_date,
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        if not rows:
            return 0
        for row in rows:
            await self._session.delete(row)
        return len(rows)

    async def clear_all_quotas(self) -> int:
        stmt = select(SellerDailyQuota)
        rows = list((await self._session.execute(stmt)).scalars().all())
        if not rows:
            return 0
        for row in rows:
            await self._session.delete(row)
        return len(rows)
