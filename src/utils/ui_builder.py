"""GDPX UI design system core for compact board-style screens."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from html import escape
from typing import Any

HEADER_ACADEMY = "🏛 ACADEMY GDPX | BOARD v.23"
HEADER_FINANCE = "🏛 ACADEMY GDPX | FINANCE v.23"
DIVIDER = "━━━━━━━━━━━━━━━━━━━━━━"
PREFIX_ITEM = "▸"

STATUS_APPROVED = "[✓]"
STATUS_REJECTED = "[×]"
STATUS_PENDING = "[⧖]"

_STATUS_BY_KEY: dict[str, str] = {
    "accepted": STATUS_APPROVED,
    "approved": STATUS_APPROVED,
    "paid": STATUS_APPROVED,
    "rejected": STATUS_REJECTED,
    "cancelled": STATUS_REJECTED,
    "pending": STATUS_PENDING,
    "in_review": STATUS_PENDING,
}


def format_phone(phone: str) -> str:
    """Return phone in visual format wrapped as HTML code."""

    normalized = (phone or "").strip() or "—"
    if normalized.startswith("+7") and len(normalized) == 12 and normalized[1:].isdigit():
        local = normalized[2:]
        pretty = f"+7 ({local[:3]}) {local[3:6]}-{local[6:8]}-{local[8:10]}"
        return f"<code>{escape(pretty)}</code>"
    return f"<code>{escape(normalized)}</code>"


def format_currency(amount: float) -> str:
    """Return amount in monospaced HTML style with tugrik sign."""

    numeric = float(amount)
    return f"<code>{numeric:.2f}</code> ₮"


def get_time_greeting(now: datetime | None = None) -> str:
    """Return RU greeting by server local hour."""

    current = now or datetime.now()
    hour = current.hour
    if 6 <= hour < 12:
        return "Доброе утро"
    if 12 <= hour < 18:
        return "Добрый день"
    if 18 <= hour < 23:
        return "Добрый вечер"
    return "Доброй ночи"


class GDPXRenderer:
    """Render core compact screens for GDPX board-style UI."""

    def render_dashboard(self, stats: Mapping[str, Any]) -> str:
        pending_count = int(stats.get("pending_count", 0) or 0)
        in_review_count = int(stats.get("in_review_count", 0) or 0)
        approved_count = int(stats.get("approved_count", 0) or 0)
        rejected_count = int(stats.get("rejected_count", 0) or 0)
        total_payout_amount = stats.get("total_payout_amount")
        actor = str(stats.get("username") or "—")
        greeting = get_time_greeting()
        lines: list[str] = [
            HEADER_ACADEMY,
            DIVIDER,
            f"⚜️ {greeting}, Проректор @{escape(actor)}",
            "Dashboard",
            f"{PREFIX_ITEM} {STATUS_PENDING} Pending: <code>{pending_count}</code>",
            f"{PREFIX_ITEM} {STATUS_PENDING} In review: <code>{in_review_count}</code>",
            f"{PREFIX_ITEM} {STATUS_APPROVED} Approved: <code>{approved_count}</code>",
            f"{PREFIX_ITEM} {STATUS_REJECTED} Rejected: <code>{rejected_count}</code>",
        ]
        if total_payout_amount is not None:
            lines.append(f"{PREFIX_ITEM} Balance: {format_currency(float(total_payout_amount))}")
        lines.append(DIVIDER)
        return "\n".join(lines)

    def render_user_profile(self, user_stats: Mapping[str, Any]) -> str:
        username = str(user_stats.get("username") or "resident")
        safe_username = escape(username)
        user_id = int(user_stats.get("user_id") or 0)
        approved_count = int(user_stats.get("approved_count") or 0)
        pending_count = int(user_stats.get("pending_count") or 0)
        rejected_count = int(user_stats.get("rejected_count") or 0)
        greeting = get_time_greeting()
        rank_label, next_target = self._rank_info(approved_count)
        remaining = max(next_target - approved_count, 0) if next_target is not None else 0
        progress = self._rank_progress_bar(approved_count, next_target)
        return "\n".join(
            [
                "🏛 ACADEMY GDPX | RESIDENT PROFILE",
                DIVIDER,
                f"⚜️ {greeting}, Резидент @{safe_username}",
                f"👤 Резидент: @{safe_username}",
                f"💳 ID:  <code>{user_id}</code>",
                "",
                f"⚜️ Статус: {rank_label}",
                (
                    f"Следующий ранг через: {remaining} шт."
                    if next_target is not None
                    else "Следующий ранг через: 0 шт."
                ),
                f"Прогресс: {progress}",
                "",
                "📊 Статистика активов:",
                f"{PREFIX_ITEM} Успешно отработано: {approved_count} шт.",
                f"{PREFIX_ITEM} В ожидании: {pending_count} шт.",
                f"{PREFIX_ITEM} Отбраковано: {rejected_count} шт.",
                DIVIDER,
            ]
        )

    def render_queue(self, submissions: Sequence[Any], *, title: str = "Queue") -> str:
        lines: list[str] = [HEADER_ACADEMY, DIVIDER, title]
        if not submissions:
            lines.extend([f"{PREFIX_ITEM} Queue is empty", DIVIDER])
            return "\n".join(lines)

        for submission in submissions:
            sid = self._pick(submission, "id", default="—")
            status = self._status_marker(self._pick(submission, "status", default="pending"))
            phone = self._pick(
                submission,
                "phone_normalized",
                "description_text",
                "phone",
                default="—",
            )
            amount = self._pick(submission, "accepted_amount", "amount", default=None)

            row = f"{PREFIX_ITEM} #{sid} {status} {format_phone(str(phone))}"
            if amount is not None:
                row = f"{row} · {format_currency(float(amount))}"
            lines.append(row)

        lines.append(DIVIDER)
        return "\n".join(lines)

    def render_queue_lobby(self, *, pending_count: int) -> str:
        lines: list[str] = [
            "🏛 ACADEMY GDPX | QUEUE",
            DIVIDER,
            f"{PREFIX_ITEM} Pending contracts: <code>{int(pending_count)}</code>",
            DIVIDER,
        ]
        return "\n".join(lines)

    def render_moderation_card(self, submission: Any, *, is_duplicate: bool = False) -> str:
        sid = self._pick(submission, "id", default="—")
        phone = self._pick(submission, "phone_normalized", "description_text", default="—")

        category_obj = self._pick(submission, "category", default=None)
        category = "Без категории"
        if category_obj is not None:
            title = getattr(category_obj, "title", None)
            if isinstance(title, str) and title.strip():
                category = escape(title.strip())

        locked_admin_obj = self._pick(submission, "locked_by_admin", default=None)
        admin_line = ""
        if locked_admin_obj is not None:
            admin_username = getattr(locked_admin_obj, "username", None)
            if isinstance(admin_username, str) and admin_username.strip():
                admin_line = f"🛡 Контроль: @{escape(admin_username.strip())}"
            else:
                admin_id = getattr(locked_admin_obj, "id", None)
                admin_line = f"🛡 Контроль: id:{admin_id}" if admin_id is not None else ""

        lines: list[str] = [
            f"🏛 ACADEMY GDPX | ASSET #{sid}",
            DIVIDER,
            f"📱 Идентификатор:  {format_phone(str(phone))}",
            f"📦 Категория: {category}",
        ]
        if admin_line:
            lines.append(admin_line)
        if is_duplicate:
            lines.append("⚠️ ВНИМАНИЕ: АКТИВ УЖЕ ФИГУРИРОВАЛ В БАЗЕ!")
        return "\n".join(lines)

    def render_in_work_list(self, submissions: Sequence[Any]) -> str:
        lines: list[str] = [
            "🏛 ACADEMY GDPX | АКТИВНЫЕ ЗАДАЧИ",
            DIVIDER,
        ]
        if not submissions:
            lines.extend([f"{PREFIX_ITEM} Нет активных контрактов.", DIVIDER])
            return "\n".join(lines)

        for submission in submissions:
            phone = self._pick(submission, "phone_normalized", "description_text", default="—")
            seller = self._pick(submission, "seller", default=None)
            username = self._username_label(seller)
            lines.append(f"{PREFIX_ITEM} 📱 {format_phone(str(phone))}  | 👤 {username}")

        lines.append(DIVIDER)
        return "\n".join(lines)

    def render_payouts(self, payouts: Sequence[Any], *, title: str = "Payouts") -> str:
        lines: list[str] = [HEADER_FINANCE, DIVIDER]
        if not payouts:
            lines.extend([f"{PREFIX_ITEM} Нет записей к выплате.", DIVIDER])
            return "\n".join(lines)

        for payout in payouts:
            username = escape(str(self._pick(payout, "username", default="—")))
            accepted_count = int(self._pick(payout, "accepted_count", default=0) or 0)
            amount_raw = self._pick(payout, "to_pay", "amount", "accepted_amount", default=0.0)
            amount = float(amount_raw)
            lines.append(
                f"🪶 {username} | 📜 {accepted_count} шт. | 💎 {format_currency(amount)}"
            )

        lines.append(DIVIDER)
        return "\n".join(lines)

    @staticmethod
    def _pick(item: Any, *keys: str, default: Any = None) -> Any:
        if isinstance(item, Mapping):
            for key in keys:
                if key in item:
                    value = item[key]
                    if value is not None:
                        return value
            return default

        for key in keys:
            if hasattr(item, key):
                value = getattr(item, key)
                if value is not None:
                    return value
        return default

    @staticmethod
    def _status_marker(status: Any) -> str:
        value = str(status).strip().lower()
        return _STATUS_BY_KEY.get(value, STATUS_PENDING)

    @staticmethod
    def _format_date(value: Any) -> str:
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d")
        text = str(value).strip()
        return text if text else "n/a"

    @staticmethod
    def _username_label(seller: Any) -> str:
        if seller is None:
            return "—"
        username = getattr(seller, "username", None)
        if isinstance(username, str) and username.strip():
            return f"@{username.strip()}"
        seller_id = getattr(seller, "id", None)
        return f"id:{seller_id}" if seller_id is not None else "—"

    @staticmethod
    def _rank_info(approved_count: int) -> tuple[str, int | None]:
        if approved_count < 10:
            return "I. Наблюдатель", 10
        if approved_count < 50:
            return "II. Резидент", 50
        if approved_count < 200:
            return "III. Доверенный", 200
        return "IV. Executive Partner", None

    @staticmethod
    def _rank_progress_bar(approved_count: int, next_target: int | None) -> str:
        total_cells = 10
        if next_target is None:
            return "[" + ("▓" * total_cells) + "]"
        if next_target <= 10:
            base = 0
        elif next_target <= 50:
            base = 10
        else:
            base = 50
        span = max(next_target - base, 1)
        progress_ratio = min(max((approved_count - base) / span, 0.0), 1.0)
        filled = int(round(progress_ratio * total_cells))
        return "[" + ("▓" * filled) + ("░" * (total_cells - filled)) + "]"
