from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.models.base import Base, TimestampMixin


class SellerDailyQuota(Base, TimestampMixin):
    """Ежедневный запрос (лимит выгрузок) для пары продавец + категория (подтип оператора), UTC."""

    __tablename__ = "seller_daily_quotas"
    __table_args__ = (
        UniqueConstraint("user_id", "category_id", "quota_date", name="uq_seller_cat_quota_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), nullable=False, index=True)
    quota_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    max_uploads: Mapped[int] = mapped_column(Integer, nullable=False)

    user = relationship("User", back_populates="daily_quotas")
    category = relationship("Category", back_populates="seller_daily_quotas")
