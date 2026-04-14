from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from src.database.models.seller_daily_quota import SellerDailyQuota
    from src.database.models.submission import Submission


class Category(Base, TimestampMixin):
    """Продукт (eSIM) — Оператор | Тип | Холд — цена за единицу в USDT."""

    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("slug", name="uq_categories_slug"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    payout_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_upload_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    is_priority: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    operator: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    sim_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    hold_condition: Mapped[str | None] = mapped_column(String(60), nullable=True)

    submissions: Mapped[list["Submission"]] = relationship("Submission", back_populates="category")
    seller_daily_quotas: Mapped[list["SellerDailyQuota"]] = relationship(
        "SellerDailyQuota", back_populates="category", cascade="all, delete-orphan"
    )

    def compose_title(self) -> str:
        parts = [p for p in (self.operator, self.sim_type, self.hold_condition) if p]
        return " | ".join(parts) if parts else self.title