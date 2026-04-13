from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.models.base import Base, TimestampMixin
from src.database.models.enums import RejectionReason, SubmissionStatus

if TYPE_CHECKING:
    from src.database.models.category import Category
    from src.database.models.publication import PublicationArchive
    from src.database.models.review_action import ReviewAction
    from src.database.models.user import User


def _enum_values(enum_cls: type[SubmissionStatus] | type[RejectionReason]) -> list[str]:
    return [item.value for item in enum_cls]


class Submission(Base, TimestampMixin):
    """Карточка материала: фото, описание, статус и ответственный админ."""

    __tablename__ = "submissions"
    __table_args__ = (
        Index("ix_submissions_status_created_at", "status", "created_at"),
        Index("ix_submissions_user_status_created", "user_id", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    admin_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    category_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("categories.id"), index=True)

    telegram_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    file_unique_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    attachment_type: Mapped[str] = mapped_column(String(16), nullable=False, default="photo", index=True)
    description_text: Mapped[str] = mapped_column(Text, nullable=False)
    phone_normalized: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status_change: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[SubmissionStatus] = mapped_column(
        Enum(SubmissionStatus, name="submission_status_enum", values_callable=_enum_values, validate_strings=True),
        nullable=False,
        default=SubmissionStatus.PENDING,
        index=True,
    )
    
    # Причины отказа
    rejection_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rejection_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    
    fixed_payout_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    accepted_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    hold_assigned: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # Строковые отношения 
    seller: Mapped["User"] = relationship("User", foreign_keys=[user_id], back_populates="submissions")
    admin: Mapped["User | None"] = relationship("User", foreign_keys=[admin_id], back_populates="assigned_submissions")
    category: Mapped["Category"] = relationship("Category", back_populates="submissions")
    review_actions: Mapped[list["ReviewAction"]] = relationship(
        "ReviewAction", back_populates="submission", cascade="all, delete-orphan"
    )
    publication: Mapped["PublicationArchive | None"] = relationship(
        "PublicationArchive", back_populates="submission", uselist=False, cascade="all, delete-orphan"
    )


class ReviewAction(Base, TimestampMixin):
    """Журнал изменений статусов и действий админа (история редактирования)."""

    __tablename__ = "review_actions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False, index=True)
    admin_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    
    from_status: Mapped[SubmissionStatus | None] = mapped_column(
        Enum(SubmissionStatus, name="submission_status_enum", values_callable=_enum_values, validate_strings=True, create_type=False),
        nullable=True,
    )
    to_status: Mapped[SubmissionStatus] = mapped_column(
        Enum(SubmissionStatus, name="submission_status_enum", values_callable=_enum_values, validate_strings=True, create_type=False),
        nullable=False,
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    submission: Mapped["Submission"] = relationship("Submission", back_populates="review_actions")
    admin: Mapped["User | None"] = relationship("User", back_populates="review_logs")