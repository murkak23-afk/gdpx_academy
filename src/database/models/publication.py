from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.models.base import Base, TimestampMixin
from src.database.models.enums import PayoutStatus


class PublicationArchive(Base, TimestampMixin):
    """Архив публикаций: запись об отправке принятого материала в приватный канал."""

    __tablename__ = "publication_archives"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    archive_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    archive_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    archived_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    submission = relationship("Submission", back_populates="publication")


class Payout(Base, TimestampMixin):
    """Выплата пользователю за период (операция конца дня)."""

    __tablename__ = "payouts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    accepted_count: Mapped[int] = mapped_column(nullable=False)
    period_key: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    period_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=PayoutStatus.PENDING.value,
        index=True
    )
    uploaded_count: Mapped[int] = mapped_column(nullable=False, default=0)
    blocked_count: Mapped[int] = mapped_column(nullable=False, default=0)
    not_a_scan_count: Mapped[int] = mapped_column(nullable=False, default=0)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    crypto_check_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    crypto_check_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    cancelled_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    cancel_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user = relationship("User", foreign_keys=[user_id], back_populates="payouts")
