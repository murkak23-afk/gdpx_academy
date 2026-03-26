from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.models.base import Base, TimestampMixin
from src.database.models.enums import RejectionReason, SubmissionStatus


def _enum_values(enum_cls: type[SubmissionStatus] | type[RejectionReason]) -> list[str]:
    """Возвращает список строковых значений enum для SQLAlchemy."""

    return [item.value for item in enum_cls]


class Submission(Base, TimestampMixin):
    """Карточка материала: фото, описание, статус и ответственный админ."""

    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)

    telegram_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    file_unique_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    attachment_type: Mapped[str] = mapped_column(String(16), nullable=False, default="photo", index=True)
    description_text: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[SubmissionStatus] = mapped_column(
        Enum(
            SubmissionStatus,
            name="submission_status_enum",
            values_callable=_enum_values,
            validate_strings=True,
        ),
        nullable=False,
        default=SubmissionStatus.PENDING,
        index=True,
    )
    rejection_reason: Mapped[RejectionReason | None] = mapped_column(
        Enum(
            RejectionReason,
            name="rejection_reason_enum",
            values_callable=_enum_values,
            validate_strings=True,
        ),
        nullable=True,
    )
    rejection_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    seller = relationship("User", foreign_keys=[user_id], back_populates="submissions")
    admin = relationship(
        "User",
        foreign_keys=[admin_id],
        back_populates="assigned_submissions",
    )
    category = relationship("Category", back_populates="submissions")
    review_actions = relationship(
        "ReviewAction",
        back_populates="submission",
        cascade="all, delete-orphan",
    )
    publication = relationship(
        "PublicationArchive",
        back_populates="submission",
        uselist=False,
        cascade="all, delete-orphan",
    )


class ReviewAction(Base, TimestampMixin):
    """Журнал изменений статусов и действий админа (история редактирования)."""

    __tablename__ = "review_actions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    from_status: Mapped[SubmissionStatus | None] = mapped_column(
        Enum(
            SubmissionStatus,
            name="submission_status_enum",
            values_callable=_enum_values,
            validate_strings=True,
        ),
        nullable=True,
    )
    to_status: Mapped[SubmissionStatus] = mapped_column(
        Enum(
            SubmissionStatus,
            name="submission_status_enum",
            values_callable=_enum_values,
            validate_strings=True,
        ),
        nullable=False,
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    submission = relationship("Submission", back_populates="review_actions")
    admin = relationship("User", back_populates="review_logs")
