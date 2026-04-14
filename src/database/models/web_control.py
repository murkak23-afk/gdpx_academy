from __future__ import annotations

from datetime import datetime
from sqlalchemy import BigInteger, ForeignKey, String, Text, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.models.base import Base, TimestampMixin

class WebAccount(Base, TimestampMixin):
    """Аккаунт для входа в веб-панель."""
    __tablename__ = "web_accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    login: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    last_login: Mapped[datetime | None] = mapped_column(default=None)

    # Связь с основным пользователем бота
    user = relationship("User", backref="web_account", uselist=False)

class ChatMessage(Base, TimestampMixin):
    """Сообщения внутренней системы поддержки."""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sender_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    recipient_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    text: Mapped[str] = mapped_column(Text)
    
    # Контекстная связь с SIM-картой (тикет)
    submission_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("submissions.id", ondelete="SET NULL"), nullable=True)
    
    is_read: Mapped[bool] = mapped_column(default=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True) # Для доп. данных

    sender = relationship("User", foreign_keys=[sender_id])
    recipient = relationship("User", foreign_keys=[recipient_id])
    submission = relationship("Submission")

class DeliveryConfig(Base, TimestampMixin):
    """Конфигурация маршрутизации выдачи: (Категория + Чат) -> Топик."""
    __tablename__ = "delivery_configs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    category_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("categories.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    thread_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    category = relationship("Category")
