"""GDPX — дизайн-система интерфейса бота.

Все экраны отрисовываются в формате HTML (parse_mode='HTML').
Единая визуальная тема: компактные карточки с emoji-маркерами статусов.

Консистентные маркеры статусов:
  ⏳ — ожидает проверки (pending)
  🔍 — на проверке (in_review)
  ✅ — одобрено (accepted)
  ❌ — отклонено (rejected)
  🚫 — заблокировано (blocked)
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from html import escape
from typing import Any

# ─── Визуальные константы ───────────────────────────────────────────
HEADER_MAIN = "🏛 <b>GDPX</b> · Панель управления"
HEADER_FINANCE = "💎 <b>GDPX</b> · Финансы"
HEADER_PROFILE = "👤 <b>GDPX</b> · Профиль резидента"
HEADER_QUEUE = "📋 <b>GDPX</b> · Очередь"
HEADER_ASSET = "📱 <b>GDPX</b> · Карточка актива"
HEADER_INWORK = "🛡 <b>GDPX</b> · В работе"
HEADER_CATCON = "⚙️ <b>GDPX</b> · Конструктор категорий"

DIVIDER = "━━━━━━━━━━━━━━━"
DIVIDER_LIGHT = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈"
PREFIX_ITEM = "▸"

# Унифицированные emoji-маркеры статусов
STATUS_EMOJI: dict[str, str] = {
    "accepted": "✅",
    "approved": "✅",
    "paid": "✅",
    "rejected": "❌",
    "cancelled": "❌",
    "blocked": "🚫",
    "not_a_scan": "🚫",
    "pending": "⏳",
    "in_review": "🔍",
}


def format_phone(phone: str) -> str:
    """Форматирует телефон в читаемый вид с HTML-моноширинным шрифтом."""
    normalized = (phone or "").strip() or "—"
    # Формат 79XXXXXXXXX (11 цифр без +)
    if normalized.isdigit() and len(normalized) == 11 and normalized.startswith("79"):
        local = normalized[1:]  # 9XXXXXXXXX
        pretty = f"+7 ({local[:3]}) {local[3:6]}-{local[6:8]}-{local[8:10]}"
        return f"<code>{escape(pretty)}</code>"
    # Совместимость: +7XXXXXXXXXX
    if normalized.startswith("+7") and len(normalized) == 12 and normalized[1:].isdigit():
        local = normalized[2:]
        pretty = f"+7 ({local[:3]}) {local[3:6]}-{local[6:8]}-{local[8:10]}"
        return f"<code>{escape(pretty)}</code>"
    return f"<code>{escape(normalized)}</code>"


def format_currency(amount: float) -> str:
    """Форматирует сумму в USDT в моноширинном стиле."""
    numeric = float(amount)
    return f"<code>{numeric:.2f}</code> USDT"


def get_time_greeting(now: datetime | None = None) -> str:
    """Русское приветствие по времени суток."""
    current = now or datetime.now()
    hour = current.hour
    if 6 <= hour < 12:
        return "Доброе утро"
    if 12 <= hour < 18:
        return "Добрый день"
    if 18 <= hour < 23:
        return "Добрый вечер"
    return "Доброй ночи"


def _status_emoji(status: Any) -> str:
    """Возвращает emoji по ключу статуса."""
    value = str(status).strip().lower()
    return STATUS_EMOJI.get(value, "⏳")


class GDPXRenderer:
    """Центральный рендерер всех экранов бота GDPX."""

    # ─── Дашборд продавца (главный экран после /start) ──────────
    def render_dashboard(self, stats: Mapping[str, Any]) -> str:
        pending = int(stats.get("pending_count", 0) or 0)
        in_review = int(stats.get("in_review_count", 0) or 0)
        approved = int(stats.get("approved_count", 0) or 0)
        rejected = int(stats.get("rejected_count", 0) or 0)
        payout = stats.get("total_payout_amount")
        payout_label = str(stats.get("payout_label") or "Баланс")
        actor = str(stats.get("username") or "—")
        greeting = get_time_greeting()

        lines: list[str] = [
            HEADER_MAIN,
            DIVIDER,
            f"⚜️ {greeting}, <b>@{escape(actor)}</b>",
            "",
            "📊 <b>Сводка по активам</b>",
            f"  ⏳ Ожидают проверки: <code>{pending}</code>",
            f"  🔍 На проверке: <code>{in_review}</code>",
            f"  ✅ Одобрено: <code>{approved}</code>",
            f"  ❌ Отклонено: <code>{rejected}</code>",
        ]
        if payout is not None:
            lines.append(f"  💰 {escape(payout_label)}: {format_currency(float(payout))}")
        lines.append(DIVIDER)
        return "\n".join(lines)

    # ─── Профиль резидента ──────────────────────────────────────
    def render_user_profile(self, user_stats: Mapping[str, Any]) -> str:
        username = str(user_stats.get("username") or "резидент")
        safe = escape(username)
        user_id = int(user_stats.get("user_id") or 0)
        approved = int(user_stats.get("approved_count") or 0)
        pending = int(user_stats.get("pending_count") or 0)
        rejected = int(user_stats.get("rejected_count") or 0)
        greeting = get_time_greeting()
        rank_label, next_target = self._rank_info(approved)
        remaining = max(next_target - approved, 0) if next_target is not None else 0
        progress = self._rank_progress_bar(approved, next_target)

        return "\n".join([
            HEADER_PROFILE,
            DIVIDER,
            f"⚜️ {greeting}, <b>@{safe}</b>",
            "",
            f"🆔 <b>ID:</b> <code>{user_id}</code>",
            f"⚜️ <b>Ранг:</b> {rank_label}",
            f"📈 <b>Прогресс:</b> {progress}",
            (
                f"  До следующего ранга: <code>{remaining}</code> шт."
                if next_target is not None
                else "  🏆 Максимальный ранг достигнут!"
            ),
            "",
            "📊 <b>Статистика активов</b>",
            f"  ✅ Успешно: <code>{approved}</code> шт.",
            f"  ⏳ Ожидают: <code>{pending}</code> шт.",
            f"  ❌ Отклонено: <code>{rejected}</code> шт.",
            DIVIDER,
        ])

    # ─── Список очереди (для админов) ───────────────────────────
    def render_queue(self, submissions: Sequence[Any], *, title: str = "Очередь") -> str:
        lines: list[str] = [HEADER_QUEUE, DIVIDER, f"📋 <b>{escape(title)}</b>"]
        if not submissions:
            lines.extend([f"{PREFIX_ITEM} <i>Очередь пуста</i>", DIVIDER])
            return "\n".join(lines)

        for sub in submissions:
            sid = self._pick(sub, "id", default="—")
            status = _status_emoji(self._pick(sub, "status", default="pending"))
            phone = self._pick(sub, "phone_normalized", "description_text", "phone", default="—")
            amount = self._pick(sub, "accepted_amount", "amount", default=None)

            row = f"{PREFIX_ITEM} #{sid} {status} {format_phone(str(phone))}"
            if amount is not None:
                row = f"{row} · {format_currency(float(amount))}"
            lines.append(row)

        lines.append(DIVIDER)
        return "\n".join(lines)

    # ─── Лобби очереди (общий счётчик) ──────────────────────────
    def render_queue_lobby(self, *, pending_count: int) -> str:
        return "\n".join([
            HEADER_QUEUE,
            DIVIDER,
            f"{PREFIX_ITEM} ⏳ Ожидают проверки: <code>{int(pending_count)}</code>",
            DIVIDER,
        ])

    # ─── Карточка актива (модерация) ────────────────────────────
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
                admin_line = f"🛡 <b>Контролёр:</b> @{escape(admin_username.strip())}"
            else:
                admin_id = getattr(locked_admin_obj, "id", None)
                admin_line = f"🛡 <b>Контролёр:</b> id:{admin_id}" if admin_id is not None else ""

        lines: list[str] = [
            f"{HEADER_ASSET} <b>#{sid}</b>",
            DIVIDER,
            f"📱 <b>Номер:</b> {format_phone(str(phone))}",
            f"📦 <b>Категория:</b> {category}",
        ]
        if admin_line:
            lines.append(admin_line)
        if is_duplicate:
            lines.append("⚠️ <b>ВНИМАНИЕ:</b> актив уже фигурировал в базе!")
        return "\n".join(lines)

    # ─── Список «В работе» ──────────────────────────────────────
    def render_in_work_list(self, submissions: Sequence[Any]) -> str:
        lines: list[str] = [HEADER_INWORK, DIVIDER]
        if not submissions:
            lines.extend([f"{PREFIX_ITEM} <i>Нет активных задач</i>", DIVIDER])
            return "\n".join(lines)

        for sub in submissions:
            phone = self._pick(sub, "phone_normalized", "description_text", default="—")
            seller = self._pick(sub, "seller", default=None)
            username = self._username_label(seller)
            lines.append(f"{PREFIX_ITEM} 📱 {format_phone(str(phone))}  │ 👤 {username}")

        lines.append(DIVIDER)
        return "\n".join(lines)

    # ─── Ведомость выплат (Chief Admin) ─────────────────────────
    def render_payouts(self, payouts: Sequence[Any], *, title: str = "Ведомость выплат") -> str:
        lines: list[str] = [
            HEADER_FINANCE,
            DIVIDER,
            f"💎 <b>{escape(title)}</b>",
        ]
        if not payouts:
            lines.extend([f"{PREFIX_ITEM} <i>Нет записей к выплате</i>", DIVIDER])
            return "\n".join(lines)

        total_amount = 0.0
        total_items = 0
        for payout in payouts:
            username = escape(str(self._pick(payout, "username", default="—")))
            accepted_count = int(self._pick(payout, "accepted_count", default=0) or 0)
            amount_raw = self._pick(payout, "to_pay", "amount", "accepted_amount", default=0.0)
            amount = float(amount_raw)
            total_amount += amount
            total_items += accepted_count
            lines.append(f"  👤 {username} │ 📜 {accepted_count} шт. │ 💰 {format_currency(amount)}")

        lines.append(DIVIDER_LIGHT)
        lines.append(f"  <b>Итого:</b> {total_items} шт. │ {format_currency(total_amount)}")
        lines.append(DIVIDER)
        return "\n".join(lines)

    # ─── Утилиты ────────────────────────────────────────────────
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
    def _format_date(value: Any) -> str:
        if isinstance(value, datetime):
            return value.strftime("%d.%m.%Y")
        text = str(value).strip()
        return text if text else "—"

    @staticmethod
    def _username_label(seller: Any) -> str:
        if seller is None:
            return "—"
        username = getattr(seller, "username", None)
        if isinstance(username, str) and username.strip():
            return f"@{username.strip()}"
        seller_id = getattr(seller, "id", None)
        return f"@{seller_id}" if seller_id is not None else "—"

    @staticmethod
    def _rank_info(approved_count: int) -> tuple[str, int | None]:
        """Система рангов: Наблюдатель → Резидент → Доверенный → Партнёр."""
        if approved_count < 10:
            return "🌱 Наблюдатель", 10
        if approved_count < 50:
            return "🏠 Резидент", 50
        if approved_count < 200:
            return "⭐ Доверенный", 200
        return "💎 Партнёр", None

    @staticmethod
    def _rank_progress_bar(approved_count: int, next_target: int | None) -> str:
        total_cells = 10
        if next_target is None:
            return "[" + ("▓" * total_cells) + "] 🏆"
        if next_target <= 10:
            base = 0
        elif next_target <= 50:
            base = 10
        else:
            base = 50
        span = max(next_target - base, 1)
        ratio = min(max((approved_count - base) / span, 0.0), 1.0)
        filled = int(round(ratio * total_cells))
        return "[" + ("▓" * filled) + ("░" * (total_cells - filled)) + "]"

    # ─── Конструктор категорий ──────────────────────────────────
    def render_cat_constructor_step(
        self,
        step_num: int,
        total_steps: int,
        title: str,
        description: str,
        *,
        current_data: dict[str, str] | None = None,
    ) -> str:
        """Рендерит шаг конструктора категорий."""
        bar_filled = step_num
        bar_empty = total_steps - step_num
        progress = "▓" * (bar_filled * 3) + "░" * (bar_empty * 3)
        lines: list[str] = [
            HEADER_CATCON,
            DIVIDER,
            f"<b>Шаг {step_num}/{total_steps}:</b> {escape(title)}",
            f"[{progress}]",
            "",
            escape(description),
        ]
        if current_data:
            lines.append("")
            lines.append(DIVIDER_LIGHT)
            for k, v in current_data.items():
                lines.append(f"  {k}: <b>{escape(v)}</b>")
        lines.append(DIVIDER)
        return "\n".join(lines)

    def render_cat_constructor_confirm(
        self,
        operator: str,
        sim_type: str,
        price: str,
    ) -> str:
        """Рендерит финальный экран подтверждения конструктора."""
        composed = f"{operator} | {sim_type}"
        lines: list[str] = [
            HEADER_CATCON,
            DIVIDER,
            "📋 <b>Проверьте данные</b>",
            "",
            f"  📡 <b>Оператор:</b> {escape(operator)}",
            f"  📂 <b>Тип:</b> {escape(sim_type)}",
            f"  💰 <b>Цена:</b> <code>{escape(price)}</code> USDT",
            "",
            DIVIDER_LIGHT,
            f"  📌 <b>Название:</b> {escape(composed)}",
            DIVIDER,
        ]
        return "\n".join(lines)

    def render_cat_list(self, categories: list[Any]) -> str:
        """Рендерит список всех категорий в стиле SPA."""
        lines: list[str] = [
            HEADER_CATCON,
            DIVIDER,
            f"📋 <b>Категории</b> · <code>{len(categories)}</code> шт.",
            "",
        ]
        if not categories:
            lines.append(f"{PREFIX_ITEM} <i>Категорий пока нет</i>")
        else:
            for c in categories[:30]:
                state = "✅" if getattr(c, "is_active", False) else "⛔"
                rate = getattr(c, "payout_rate", 0)
                limit_raw = getattr(c, "total_upload_limit", None)
                limit_str = "∞" if limit_raw is None else str(limit_raw)
                lines.append(
                    f"  {state} <b>{escape(str(c.title))}</b>"
                    f" · <code>{rate}</code> USDT · лимит: {limit_str}"
                )
            if len(categories) > 30:
                lines.append(f"  <i>… и ещё {len(categories) - 30}</i>")
        lines.append(DIVIDER)
        return "\n".join(lines)
