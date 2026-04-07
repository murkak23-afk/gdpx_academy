"""Leaderboard settings persisted in DB (single-row config table)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database.models.base import Base


class LeaderboardSettings(Base):
    """Single-row configuration table for the weekly leaderboard prize."""

    __tablename__ = "leaderboard_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prize_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prize_text: Mapped[str | None] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
