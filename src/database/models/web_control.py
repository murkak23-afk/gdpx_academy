from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from sqlalchemy import BigInteger, ForeignKey, String, Text, Boolean, JSON, Integer, Numeric
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

class SupportTicket(Base, TimestampMixin):
    """Тикет (тема обсуждения), привязанный к объекту."""
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    creator_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    
    # К какому объекту привязан тикет (опционально)
    category_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    submission_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("submissions.id", ondelete="SET NULL"), nullable=True)
    
    subject: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="open") # open, resolved, closed

    creator = relationship("User")
    messages = relationship("ChatMessage", back_populates="ticket", cascade="all, delete-orphan")

class ChatMessage(Base, TimestampMixin):
    """Сообщения внутренней системы поддержки."""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(Integer, ForeignKey("support_tickets.id", ondelete="CASCADE"))
    sender_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    
    text: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(default=False)

    ticket = relationship("SupportTicket", back_populates="messages")
    sender = relationship("User")

class DeliveryConfig(Base, TimestampMixin):
    """Конфигурация маршрутизации выдачи: (Пользователь + Категория) -> Чат + Топик."""
    __tablename__ = "delivery_configs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("categories.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    thread_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    user = relationship("User")
    category = relationship("Category")

class SimbuyerPrice(Base, TimestampMixin):
    """Персональные цены для конкретных покупателей."""
    __tablename__ = "simbuyer_prices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("categories.id", ondelete="CASCADE"), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    user = relationship("User")
    category = relationship("Category")

class LeaderboardSettings(Base, TimestampMixin):
    """Настройки доски лидеров и призового фонда."""
    __tablename__ = "leaderboard_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    prize_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    prize_text: Mapped[str | None] = mapped_column(String(512))

