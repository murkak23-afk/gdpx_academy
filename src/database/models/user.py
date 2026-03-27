from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Enum, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.models.base import Base, TimestampMixin
from src.database.models.enums import UserLanguage, UserRole


def _enum_values(enum_cls: type[UserLanguage] | type[UserRole]) -> list[str]:
    """Возвращает список строковых значений enum для SQLAlchemy."""

    return [item.value for item in enum_cls]


class User(Base, TimestampMixin):
    """Пользователь Telegram: селлер или владелец (chief admin)."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("telegram_id", name="uq_users_telegram_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[UserLanguage] = mapped_column(
        Enum(
            UserLanguage,
            name="user_language_enum",
            values_callable=_enum_values,
            validate_strings=True,
        ),
        nullable=False,
        default=UserLanguage.RU,
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            name="user_role_enum",
            values_callable=_enum_values,
            validate_strings=True,
        ),
        nullable=False,
        default=UserRole.SELLER,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    is_restricted: Mapped[bool] = mapped_column(nullable=False, default=False, index=True)
    duplicate_timeout_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    captcha_answer: Mapped[str | None] = mapped_column(String(16), nullable=True)
    captcha_attempts: Mapped[int] = mapped_column(nullable=False, default=0)

    payout_details: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pending_balance: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
    )
    total_paid: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
    )

    submissions = relationship(
        "Submission",
        foreign_keys="Submission.user_id",
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    assigned_submissions = relationship(
        "Submission",
        foreign_keys="Submission.admin_id",
        back_populates="admin",
    )
    locked_submissions = relationship(
        "Submission",
        foreign_keys="Submission.locked_by_admin_id",
        back_populates="locked_by_admin",
    )
    review_logs = relationship(
        "ReviewAction",
        foreign_keys="ReviewAction.admin_id",
        back_populates="admin",
    )
    payouts = relationship(
        "Payout",
        foreign_keys="Payout.user_id",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    daily_quotas = relationship(
        "SellerDailyQuota",
        back_populates="user",
        cascade="all, delete-orphan",
    )
