from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    """Роли в системе."""

    SELLER = "seller"
    ADMIN = "admin"
    CHIEF_ADMIN = "chief_admin"
    SIM_ROOT = "sim_root"


class UserLanguage(StrEnum):
    """Поддерживаемые языки интерфейса. Бот работает только на русском."""

    RU = "ru"


class SubmissionStatus(StrEnum):
    """Статусы симки контента."""

    PENDING = "pending"
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
