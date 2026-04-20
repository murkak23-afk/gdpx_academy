from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List
from sqlalchemy import BigInteger, DateTime, String, JSON, Numeric, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.database.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.database.models.submission import Submission, ReviewAction
    from src.database.models.web_control import SimbuyerPrice, SellerDailyQuota, Payout

class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("telegram_id", name="uq_users_telegram_id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255))
    language: Mapped[str] = mapped_column(String(16), default="ru")
    role: Mapped[str] = mapped_column(String(32), default="seller", index=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    is_restricted: Mapped[bool] = mapped_column(default=False)
    has_accepted_codex: Mapped[bool] = mapped_column(default=False)
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pseudonym: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_incognito: Mapped[bool] = mapped_column(default=False)
    is_silent_mode: Mapped[bool] = mapped_column(default=False)
    notification_preference: Mapped[str] = mapped_column(String(32), default="full")
    favorite_categories: Mapped[list[int]] = mapped_column(JSON, default=list)
    badges: Mapped[list[str]] = mapped_column(JSON, default=list)
    payout_details: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pending_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    total_paid: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    submissions: Mapped[List["Submission"]] = relationship("Submission", foreign_keys="Submission.user_id", back_populates="seller")
    assigned_submissions: Mapped[List["Submission"]] = relationship("Submission", foreign_keys="Submission.admin_id", back_populates="admin")
    review_logs: Mapped[List["ReviewAction"]] = relationship("ReviewAction", foreign_keys="ReviewAction.admin_id", back_populates="admin")
    prices: Mapped[List["SimbuyerPrice"]] = relationship("SimbuyerPrice", back_populates="user")
    daily_quotas: Mapped[List["SellerDailyQuota"]] = relationship("SellerDailyQuota", back_populates="user")
    payouts: Mapped[List["Payout"]] = relationship("Payout", foreign_keys="Payout.user_id", back_populates="user")
