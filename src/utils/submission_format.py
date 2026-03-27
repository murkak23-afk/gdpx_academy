"""Единый человекочитаемый заголовок заявки: «Номер — Категория»."""

from __future__ import annotations

from html import escape

from src.database.models.enums import SubmissionStatus
from src.database.models.submission import Submission
from src.utils.phone_norm import mask_phone_public


def format_submission_title_from_parts(description_text: str | None, category_title: str | None) -> str:
    phone = (description_text or "").strip() or "—"
    cat = (category_title or "").strip() or "Без категории"
    return f"{phone} — {cat}"


def format_submission_title(submission: Submission) -> str:
    """Требует загруженный `submission.category` или корректный `category_id` в БД."""

    phone = (submission.description_text or "").strip() or "—"
    if submission.category is not None:
        cat = (submission.category.title or "").strip() or "Без категории"
    else:
        cat = "Без категории"
    return f"{phone} — {cat}"


def format_submission_title_anonymized(submission: Submission) -> str:
    """Подпись для рабочих чатов: маска номера и категория, без персональных данных."""

    phone = (submission.description_text or "").strip() or "—"
    masked = mask_phone_public(phone)
    if submission.category is not None:
        cat = (submission.category.title or "").strip() or "Без категории"
    else:
        cat = "Без категории"
    return f"{masked} — {cat}"


def submission_status_emoji_line(status: SubmissionStatus) -> str:
    """Короткая строка статуса с цветовым маркером."""

    if status == SubmissionStatus.PENDING:
        return "⚪ Ожидание"
    if status == SubmissionStatus.IN_REVIEW:
        return "🟡 В работе"
    if status == SubmissionStatus.ACCEPTED:
        return "🟢 Готово"
    return "🔴 Брак"


def format_phone_category_html(description_text: str | None, category_title: str | None) -> str:
    """Номер в &lt;code&gt; (копирование одним тапом) и экранированная категория."""

    phone = (description_text or "").strip() or "—"
    cat = escape((category_title or "").strip() or "Без категории")
    return f"📱 <code>{escape(phone)}</code> — {cat}"


def duplicate_warning_html(submission: Submission) -> str:
    if not getattr(submission, "is_duplicate", False):
        return ""
    return "<b>⚠️ ВНИМАНИЕ: ЭТОТ НОМЕР УЖЕ БЫЛ В БОТЕ РАНЕЕ!</b>"


def moderation_admin_card_html(
    *,
    submission: Submission,
    seller_label: str,
    category_title: str,
    status_line: str | None = None,
    lock_line: str = "",
    hint_block: str = "",
) -> str:
    """Единый HTML-текст карточки для админов (очередь/в работе/поиск)."""

    st = status_line if status_line is not None else submission_status_emoji_line(submission.status)
    parts: list[str] = []
    if hint_block:
        parts.append(hint_block)
    parts.append(f"Submission #{submission.id}")
    parts.append(f"Продавец: {escape(seller_label)}")
    parts.append(format_phone_category_html(submission.description_text, category_title))
    parts.append(st)
    if getattr(submission, "is_duplicate", False):
        parts.append(duplicate_warning_html(submission))
    if lock_line:
        parts.append(lock_line.strip())
    return "\n\n".join(p for p in parts if p)
