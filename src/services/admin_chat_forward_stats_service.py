from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.admin_chat_forward_daily import AdminChatForwardDaily


class AdminChatForwardStatsService:
    """Учёт пересылок в чаты по telegram_chat_id (по дням UTC)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_forwards_for_telegram_chat(self, telegram_chat_id: int, delta: int) -> None:
        """Увеличивает счётчик за сегодня (UTC) для указанного chat_id."""

        if delta <= 0:
            return
        today = datetime.now(timezone.utc).date()
        row_stmt = select(AdminChatForwardDaily).where(
            AdminChatForwardDaily.telegram_chat_id == telegram_chat_id,
            AdminChatForwardDaily.stat_date == today,
        )
        row = (await self._session.execute(row_stmt)).scalar_one_or_none()
        if row is None:
            self._session.add(
                AdminChatForwardDaily(
                    telegram_chat_id=telegram_chat_id,
                    stat_date=today,
                    forward_count=delta,
                )
            )
        else:
            row.forward_count += delta

    async def get_counts_last_7_days(self, telegram_chat_id: int) -> dict[date, int]:
        """Счётчики по дням за последние 7 календарных дней (UTC), включая сегодня."""

        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=6)
        stmt = select(AdminChatForwardDaily).where(
            AdminChatForwardDaily.telegram_chat_id == telegram_chat_id,
            AdminChatForwardDaily.stat_date >= start,
            AdminChatForwardDaily.stat_date <= today,
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        out: dict[date, int] = {start + timedelta(days=i): 0 for i in range(7)}
        for r in rows:
            out[r.stat_date] = r.forward_count
        return out
