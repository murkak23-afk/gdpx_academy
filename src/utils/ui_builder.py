"""GDPX — дизайн-система интерфейса бота.

Все экраны отрисовываются в формате HTML (parse_mode='HTML').
Единая визуальная тема: "Monochrome Blocks". Брутальная геометрия, 
крупные индикаторы, массивные разделители.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from html import escape
from typing import Any

# ─── Визуальные константы (Premium / Apple Style) ───────────────────
HEADER_MAIN = "❖ <b>GDPX Academy</b>"
HEADER_ADMIN_MAIN = "❖ <b>GDPX Academy</b> ⸻ Управление"
HEADER_FINANCE = "❖ <b>GDPX Academy</b> ⸻ Финансы"
HEADER_PROFILE = "👤 <b>Кабинет Поставщика</b>"
HEADER_QUEUE = "❖ <b>GDPX Academy</b> ⸻ Очередь оценки"
HEADER_ASSET = "❖ <b>GDPX Academy</b> ⸻ Актив"
HEADER_INWORK = "❖ <b>GDPX Academy</b> ⸻ Операционная зона"
HEADER_SEARCH = "❖ <b>GDPX Academy</b> ⸻ Поиск по базе"
HEADER_CATCON = "❖ <b>GDPX Academy</b> ⸻ Настройки"

DIVIDER = "━━━━━━━━━━━━━━━━━━━━"
DIVIDER_LIGHT = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈"
PREFIX_ITEM = "◾️"

# Статусы переводим в премиальный монохром
STATUS_EMOJI: dict[str, str] = {
    "accepted": "◾️",     # Успех теперь не кричит, а аккуратно отмечается
    "approved": "◾️",
    "paid": "◾️",
    "rejected": "▫️",     # Отказ — пустой маркер или крестик ✕
    "cancelled": "▫️",
    "blocked": "✕",      
    "not_a_scan": "✕",
    "pending": "⏳",      # Ожидание 
    "in_review": "🔄",    # В процессе
}


def format_phone(phone: str) -> str:
    """Форматирует телефон в читаемый вид с HTML-моноширинным шрифтом."""
    normalized = (phone or "").strip() or "—"
    if normalized.isdigit() and len(normalized) == 11 and normalized.startswith("79"):
        local = normalized[1:]
        pretty = f"+7 ({local[:3]}) {local[3:6]}-{local[6:8]}-{local[8:10]}"
        return f"<code>{escape(pretty)}</code>"
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
    """Лаконичные приветствия в стиле Apple."""
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
    """Возвращает premium-символ по ключу статуса."""
    value = str(status).strip().lower()
    return STATUS_EMOJI.get(value, "▪️")


class GDPXRenderer:

    def render_user_profile(self, user_stats: Mapping[str, Any], user_id: int) -> str:
        """Отрисовка личного кабинета (Касса и Статус)."""
        actor = str(user_stats.get("username") or user_stats.get("telegram_id") or user_stats.get("user_id") or "—")
        safe_actor = "Скрытый профиль" if actor.lower() in ("resident", "резидент", "—") else (escape(actor) if actor.isdigit() else f"@{escape(actor)}")

        approved = int(user_stats.get("approved_count") or 0)
        pending = int(user_stats.get("pending_count") or 0)
        rejected = int(user_stats.get("rejected_count") or 0)
        
        rank_label, next_target = self._rank_info(approved)
        remaining = max(next_target - approved, 0) if next_target is not None else 0
        progress = self._rank_progress_bar(approved, next_target)
        
        return "\n".join([
            HEADER_PROFILE,
            DIVIDER,
            f"ID: <code>{user_id}</code>",
            f"Уровень доступа: <b>{rank_label}</b>",
            "",
            "<b>Статистика ваших продаж:</b>",
            f" ◾️ Успешно выкуплено: <code>{approved}</code>",
            f" ◾️ На оценке: <code>{pending}</code>",
            f" ◾️ Отклонено (Брак): <code>{rejected}</code>",
            "",
            f"<b>План сдачи:</b> {progress}",
            (
                f" ╰ <i>Осталось до повышения: <code>{remaining}</code> шт.</i>"
                if next_target is not None
                else " ╰ ▫️ <i>Максимальный статус достигнут.</i>"
            ),
            DIVIDER,
        ])

    def render_dashboard(self, stats: Mapping[str, Any]) -> str:
        """Стартовый экран (Витрина выкупа)."""
        approved = int(stats.get("approved_count", 0) or 0)
        pending = int(stats.get("pending_count", 0) or 0)
        in_review = int(stats.get("in_review_count", 0) or 0)
        rejected = int(stats.get("rejected_count", 0) or 0)
        payout = stats.get("total_payout_amount")
        
        actor = str(stats.get("username") or stats.get("telegram_id") or stats.get("user_id") or "—")
        safe_actor = "Скрытый профиль" if actor.lower() in ("resident", "резидент", "—") else (escape(actor) if actor.isdigit() else f"@{escape(actor)}")
        
        greeting = get_time_greeting()
        lines: list[str] = [
            HEADER_MAIN,
            DIVIDER,
            "<b>Премиальный выкуп eSIM. Ничего лишнего.</b>",
            "",
            f"{greeting}, <b>{safe_actor}</b>. Добро пожаловать в рабочую среду GDPX.",
            "",
            "▫️ <b>Специализация:</b> Ежедневный выкуп eSIM.",
            "▫️ <b>Цикл сделки:</b> Приём 24/7 ⸻ Фиксация ⸻ Вечерний расчёт",
            "",
            "▫️ <b>Статус линии:</b> Прием разрешен",
            DIVIDER,
            "<i>Используйте меню ниже для управления активами.</i>",
            DIVIDER,
        ]
        return "\n".join(lines)


    def render_queue(self, submissions: Sequence[Any], *, title: str = "Буфер материала") -> str:
        lines: list[str] = [HEADER_QUEUE, DIVIDER, f"▪️ <b>{escape(title)}</b>"]
        if not submissions:
            lines.extend([f" 🔲 <i>Буфер пуст</i>", DIVIDER])
            return "\n".join(lines)

        for sub in submissions:
            sid = self._pick(sub, "id", default="—")
            status = _status_emoji(self._pick(sub, "status", default="pending"))
            phone = self._pick(sub, "phone_normalized", "description_text", "phone", default="—")
            amount = self._pick(sub, "accepted_amount", "amount", default=None)

            row = f" {status} {sid} │ {format_phone(str(phone))}"
            if amount is not None:
                row = f"{row} · {format_currency(float(amount))}"
            lines.append(row)

        lines.append(DIVIDER)
        return "\n".join(lines)

    def render_queue_lobby(self, *, pending_count: int) -> str:
        return "\n".join([
            HEADER_QUEUE,
            DIVIDER,
            f"🔲 <b>Ожидает синхронизации:</b> <code>{int(pending_count)}</code>",
            DIVIDER,
        ])

    def render_moderation_card(self, submission: Any, *, is_duplicate: bool = False) -> str:
        sid = self._pick(submission, "id", default="—")
        phone = self._pick(submission, "phone_normalized", "description_text", default="—")
        seller = self._pick(submission, "seller", default=None)
        if seller is not None:
            username = getattr(seller, "username", None)
            if isinstance(username, str) and username.strip():
                seller_label = f"@{username.strip()}"
            else:
                seller_id = getattr(seller, "id", None)
                seller_label = f"id:{seller_id}" if seller_id is not None else "—"
        else:
            seller_label = "—"
        category_obj = self._pick(submission, "category", default=None)
        category = "Без кластера"
        if category_obj is not None:
            title = getattr(category_obj, "title", None)
            if isinstance(title, str) and title.strip():
                category = escape(title.strip())
        lines: list[str] = [
            f"{HEADER_ASSET} <b>{sid}</b>",
            DIVIDER,
            f"▪️ <b>Линия связи:</b> {format_phone(str(phone))}",
            f"▪️ <b>Источник:</b> {seller_label}",
            f"▪️ <b>Кластер:</b> {category}",
        ]
        if is_duplicate:
            lines.append(" ╰ ❌ <i>Отказ: дублирование в реестре пула</i>")
        return "\n".join(lines)

    def render_in_work_list(self, submissions: Sequence[Any]) -> str:
        lines: list[str] = [HEADER_INWORK, DIVIDER]
        if not submissions:
            lines.extend([f" 🔲 <i>Активных сессий нет</i>", DIVIDER])
            return "\n".join(lines)

        for sub in submissions:
            phone = self._pick(sub, "phone_normalized", "description_text", default="—")
            seller = self._pick(sub, "seller", default=None)
            username = self._username_label(seller)
            lines.append(f" 🔳 {format_phone(str(phone))}  │ {username}")

        lines.append(DIVIDER)
        return "\n".join(lines)

    def render_admin_dashboard(self, stats: Mapping[str, Any]) -> str:
        """Главная панель управления (Admin Hub)."""
        pending = int(stats.get("pending_count", 0) or 0)
        in_review = int(stats.get("in_review_count", 0) or 0)
        approved = int(stats.get("approved_count", 0) or 0)
        rejected = int(stats.get("rejected_count", 0) or 0)
        
        actor = str(stats.get("username") or stats.get("telegram_id") or "—")
        safe_actor = f"@{escape(actor)}" if not actor.isdigit() else escape(actor)
        
        has_epoch = bool(stats.get("has_epoch", False))
        greeting = get_time_greeting()
        cycle_note = " <i>(текущий цикл)</i>" if has_epoch else ""

        return "\n".join([
            HEADER_ADMIN_MAIN,
            DIVIDER,
            "<b>Управление инфраструктурой Синдиката.</b>",
            "",
            f"{greeting}, <b>{safe_actor}</b>. Система функционирует в штатном режиме.",
            "",
            "<b>Состояние узлов:</b>",
            f" ⏳ Ожидают аудита: <code>{pending}</code>",
            f" 🔄 Активные сессии: <code>{in_review}</code>",
            f" ◾️ Выкуплено: <code>{approved}</code>{cycle_note}",
            f" ▫️ Отклонено: <code>{rejected}</code>{cycle_note}",
            DIVIDER,
        ])

    def render_inwork_hub(
        self,
        items: Sequence[Any],
        *,
        is_chief: bool = False,
        index_offset: int = 0,
    ) -> str:
        lines: list[str] = [HEADER_INWORK, DIVIDER]
        if not items:
            label = "В системе нет активных сессий" if is_chief else "У вас нет открытых сессий"
            lines.extend([f" 🔲 <i>{label}</i>", DIVIDER])
            return "\n".join(lines)
        label = "Глобальный пул анализа" if is_chief else "Ваш локальный пул"
        lines.append(f"▪️ <b>{label}</b>")
        lines.append("")
        for idx, item in enumerate(items, start=index_offset + 1):
            phone = self._pick(item, "description_text", "phone_normalized", default="—")
            phone_str = (str(phone) or "").strip() or "—"
            seller = self._pick(item, "seller", default=None)
            seller_label = self._username_label(seller)
            if seller_label == "—":
                uid = self._pick(item, "user_id", default="?")
                seller_label = str(uid)
            if is_chief:
                locked_admin = self._pick(item, "locked_by_admin", default=None)
                if locked_admin is not None:
                    fn = getattr(locked_admin, "first_name", None)
                    aid = getattr(locked_admin, "id", None)
                    admin_name = str(fn or (f"id:{aid}" if aid else "—"))
                else:
                    admin_name = "—"
                lines.append(
                    f" {idx}. <code>{escape(phone_str[:22])}</code>"
                    f"  │ {seller_label}"
                    f"  │ <b>{escape(admin_name)}</b>"
                )
            else:
                lines.append(
                    f" {idx}. <code>{escape(phone_str[:22])}</code>"
                    f"  │ {seller_label}"
                )
        lines.append(DIVIDER)
        return "\n".join(lines)

    def render_inwork_search_prompt(self) -> str:
        return "\n".join([
            HEADER_SEARCH,
            DIVIDER,
            "",
            "▪️ Введите маску для сканирования сети:",
            f"  ▫️ Полный формат: <code>+7XXXXXXXXXX</code>",
            f"  ▫️ Индекс: <code>1234</code>",
            DIVIDER,
        ])

    def render_payout_history(
        self,
        items: Sequence[Any],
        *,
        page: int,
        total: int,
        page_size: int,
    ) -> str:
        max_page = max((total - 1) // page_size, 0)
        lines: list[str] = [
            HEADER_FINANCE,
            DIVIDER,
            f"▪️ <b>Реестр транзакций</b>  ·  стр. {page + 1}/{max_page + 1}",
            "",
        ]
        if not items:
            lines.extend([f" 🔲 <i>Транзакции отсутствуют</i>", DIVIDER])
            return "\n".join(lines)

        for p in items:
            period = str(self._pick(p, "period_key", default="—"))
            amount = float(self._pick(p, "amount", default=0))
            status_raw = str(self._pick(p, "status", default="pending"))
            status_val = status_raw.split(".")[-1].lower()
            emoji = _status_emoji(status_val)
            check_url = self._pick(p, "crypto_check_url", default=None)

            row = f" {emoji} <code>{escape(period)}</code>  │  {format_currency(amount)}"
            if check_url:
                row += f"\n  ╰ ▫️ <a href=\"{escape(str(check_url))}\">Хэш транзакции</a>"
            lines.append(row)

        lines.append(DIVIDER)
        return "\n".join(lines)

    def render_payouts(self, payouts: Sequence[Any], *, title: str = "Реестр распределения") -> str:
        lines: list[str] = [
            HEADER_FINANCE,
            DIVIDER,
            f"▪️ <b>{escape(title)}</b>",
        ]
        if not payouts:
            lines.extend([f" 🔲 <i>Ордеры на распределение отсутствуют</i>", DIVIDER])
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
            lines.append(f" ▪️ {username} │ {accepted_count} шт. │ {format_currency(amount)}")

        lines.append(DIVIDER_LIGHT)
        lines.append(f" ⬛️ <b>Итоговая ликвидность:</b> {total_items} шт. │ {format_currency(total_amount)}")
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
        # Убираем слово "пула" для чистоты
        if approved_count < 10: return "Ассоциат", 10
        if approved_count < 50: return "Резидент", 50
        if approved_count < 200: return "Вендор", 200
        return "Эксклюзив", None

    @staticmethod
    def _rank_progress_bar(approved_count: int, next_target: int | None) -> str:
        """Индикатор загрузки сети (Apple style blocks)."""
        total_cells = 10
        if next_target is None:
            return "⬛️" * total_cells 
        if next_target <= 10: base = 0
        elif next_target <= 50: base = 10
        else: base = 50
            
        span = max(next_target - base, 1)
        ratio = min(max((approved_count - base) / span, 0.0), 1.0)
        filled = int(round(ratio * total_cells))
        return ("⬛️" * filled) + ("⬜️" * (total_cells - filled))

    def render_cat_constructor_step(
        self,
        step_num: int,
        total_steps: int,
        title: str,
        description: str,
        *,
        current_data: dict[str, str] | None = None,
    ) -> str:
        bar_filled = step_num
        bar_empty = total_steps - step_num
        progress = "■" * bar_filled + "□" * bar_empty
        lines: list[str] = [
            HEADER_CATCON,
            DIVIDER,
            f"▪️ <b>Итерация {step_num}/{total_steps}:</b> {escape(title)}",
            f" ╰ {progress}",
            "",
            escape(description),
        ]
        if current_data:
            lines.append("")
            lines.append(DIVIDER_LIGHT)
            for k, v in current_data.items():
                lines.append(f" ▫️ {k}: <b>{escape(v)}</b>")
        lines.append(DIVIDER)
        return "\n".join(lines)

    def render_cat_constructor_confirm(
        self,
        operator: str,
        sim_type: str,
        price: str,
    ) -> str:
        composed = f"{operator} | {sim_type}"
        lines: list[str] = [
            HEADER_CATCON,
            DIVIDER,
            "▪️ <b>Параметры кластера</b>",
            "",
            f" ▫️ <b>Оператор:</b> {escape(operator)}",
            f" ▫️ <b>Архитектура:</b> {escape(sim_type)}",
            f" ▫️ <b>Ставка:</b> <code>{escape(price)}</code> USDT",
            "",
            DIVIDER_LIGHT,
            f" ⬛️ <b>Регистрация:</b> {escape(composed)}",
            DIVIDER,
        ]
        return "\n".join(lines)

    def render_cat_list(self, categories: list[Any]) -> str:
        lines: list[str] = [
            HEADER_CATCON,
            DIVIDER,
            f"▪️ <b>Активные кластеры сети</b> · <code>{len(categories)}</code> ед.",
            "",
        ]
        if not categories:
            lines.append(f" 🔲 <i>Кластеры не сконфигурированы</i>")
        else:
            for c in categories[:30]:
                state = "⬛️" if getattr(c, "is_active", False) else "❌"
                rate = getattr(c, "payout_rate", 0)
                limit_raw = getattr(c, "total_upload_limit", None)
                limit_str = "∞" if limit_raw is None else str(limit_raw)
                lines.append(
                    f" {state} <b>{escape(str(c.title))}</b>"
                    f" · <code>{rate}</code> USDT · лимит: {limit_str}"
                )
            if len(categories) > 30:
                lines.append(f"  ╰ <i>… и ещё {len(categories) - 30} узлов скрыто</i>")
        lines.append(DIVIDER)
        return "\n".join(lines)