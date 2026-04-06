from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.models.base import Base, TimestampMixin


class Category(Base, TimestampMixin):
    """Продукт (eSIM) — Оператор | Тип | Холд — цена за единицу в USDT."""

    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("slug", name="uq_categories_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    payout_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_upload_limit: Mapped[int | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    is_priority: Mapped[bool] = mapped_column(nullable=False, default=False)


    # Конструктор категории: Оператор | Тип | Холд
    operator: Mapped[str | None] = mapped_column(String(60), nullable=True)
    sim_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    hold_condition: Mapped[str | None] = mapped_column(String(60), nullable=True)

    submissions = relationship("Submission", back_populates="category")
    seller_daily_quotas = relationship(
        "SellerDailyQuota",
        back_populates="category",
        cascade="all, delete-orphan",
    )

    def compose_title(self) -> str:
        """Собирает человекочитаемый title из компонентов конструктора."""
        parts = [p for p in (self.operator, self.sim_type, self.hold_condition) if p]
        return " | ".join(parts) if parts else self.title
