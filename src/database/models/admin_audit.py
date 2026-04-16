from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.models.base import Base, TimestampMixin


class AdminAuditLog(Base, TimestampMixin):
    """Журнал действий администраторов."""

    __tablename__ = "admin_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Связь с администратором
    admin = relationship("User")
