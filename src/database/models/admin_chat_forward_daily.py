from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.database.models.base import Base


class AdminChatForwardDaily(Base):
    """Счётчик пересылок материалов в чат по дням (UTC), по telegram chat id."""

    __tablename__ = "admin_chat_forward_daily"
    __table_args__ = (UniqueConstraint("telegram_chat_id", "stat_date", name="uq_forward_daily_tgchat_day"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    forward_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
