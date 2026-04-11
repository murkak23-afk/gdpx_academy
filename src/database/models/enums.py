from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    """Роли в системе."""

    SELLER = "seller"
    ADMIN = "admin"
    OWNER = "owner"
    SIM_ROOT = "sim_root"
    SIMBUYER = "simbuyer"


class UserLanguage(StrEnum):
    """Поддерживаемые языки интерфейса. Бот работает только на русском."""

    RU = "ru"


class SubmissionStatus(StrEnum):
    """Статусы симки контента."""

    PENDING = "pending"
    IN_WORK = "in_work"
    WAIT_CONFIRM = "wait_confirm" # Потенциально отработанные (через час)
    IN_REVIEW = "in_review"
    REJECTED = "rejected"
    ACCEPTED = "accepted"
    BLOCKED = "blocked"
    NOT_A_SCAN = "not_a_scan"


class RejectionReason(StrEnum):
    """Причины отклонения контента."""

    DUPLICATE = "duplicate"
    QUALITY = "quality"
    RULES_VIOLATION = "rules_violation"
    OTHER = "other"


class PayoutStatus(StrEnum):
    """Статусы записи выплаты."""

    PENDING = "pending"
    PAID = "paid"
    CANCELLED = "cancelled"


class NotificationPreference(StrEnum):
    """Предпочтения по уведомлениям."""

    FULL = "full"        # О каждой проверке
    SUMMARY = "summary"  # Итог за день
    NONE = "none"        # Без уведомлений
