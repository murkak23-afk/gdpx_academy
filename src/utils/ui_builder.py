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
HEADER_MAIN = "❖ <b>GDPX // ACADEMY</b>  ─ Terminal v2.3" 
HEADER_ADMIN_MAIN = "❖ <b>GDPX // ACADEMY</b> ─ COMMAND NODE"
HEADER_FINANCE = "❖ <b>GDPX // ACADEMY</b> ─ FINANCE"
HEADER_PROFILE = "🀄️ <b>ПРОФИЛЬ АГЕНТА</b>"
HEADER_QUEUE = "❖ <b>GDPX // ACADEMY</b> ─ DEFECTATION BUFFER"
HEADER_INWORK = "❖ <b>GDPX // ACADEMY</b> ─ OPERATION ZONE"
HEADER_SEARCH = "❖ <b>GDPX // ACADEMY</b> ─ GLOBAL SEARCH"
HEADER_CATCON = "❖ <b>GDPX // ACADEMY</b> ─ CONFIGURATION"
HEADER_ASSET = "❖ <b>GDPX // ACADEMY</b> ─ ASSET"

DIVIDER = "━━━━━━━━━━━━━━━━━━━━"
DIVIDER_LIGHT = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈"
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
    """Лаконичные приветствия в стиле терминала."""
    current = now or datetime.now()
    hour = current.hour
    if 6 <= hour < 12:
        return "Утренняя сессия"
    if 12 <= hour < 18:
        return "Дневная сессия"
    if 18 <= hour < 23:
        return "Вечерняя сессия"
    return "Ночная сессия"


def _status_emoji(status: Any) -> str:
    """Возвращает premium-символ по ключу статуса."""
    value = str(status).strip().lower()
    return STATUS_EMOJI.get(value, "▪️")


class GDPXRenderer:

    def render_user_profile(self, user_stats: Mapping[str, Any], user_id: int) -> str:
        """Отрисовка личного кабинета (Касса и Статус)."""

        approved = int(user_stats.get("approved_count") or 0)
        pending = int(user_stats.get("pending_count") or 0)
        rejected = int(user_stats.get("rejected_count") or 0)
        
        rank_label, next_target = self._rank_info(approved)
        remaining = max(next_target - approved, 0) if next_target is not None else 0
        progress = self._rank_progress_bar(approved, next_target)
        
        return "\n".join([
            HEADER_PROFILE,
            DIVIDER,
            f"🪪 ИДЕНТИФИКАТОР: <code>{user_id}</code>",
            f"🏆 УРОВЕНЬ ДОСТУПА: <b>{rank_label}</b>",
            "",
            "📊 <b>ОПЕРАЦИОННАЯ СВОДКА:</b>",
            f" ◾️ Успешно выкуплено: <code>{approved}</code>",
            f" 🔄 В процессе оценки: <code>{pending}</code>",
            f" ▫️ Отклонено(брак): <code>{rejected}</code>",
            "",
            f"<b>ВЕКТОР РАЗВИТИЯ:</b> {progress}",
            (
                f" ╰ <i>Цель следующего ранга: <code>{remaining}</code> шт.</i>"
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
        safe_actor = "INCOGNITO" if actor.lower() in ("resident", "резидент", "—") else (escape(actor) if actor.isdigit() else f"@{escape(actor)}")
        
        greeting = get_time_greeting()
        lines: list[str] = [
            HEADER_MAIN,
            DIVIDER,
            f"🃏 <b>CEЛЛЕР:</b> <code>{safe_actor}</code>",
            "▫️ <b>СТАТУС:</b> <code>АКТИВЕН</code>",
            "",
            f"{greeting}, cоединение установлено.",
            "",
            "Добро пожаловать в закрытый контур Академии.",
            "",
            "❂ <b>ЭКОСИСТЕМА GDPX:</b>",
            "╰ Мы даём знания - вы производите актив - мы забираем весь объём.",
            "",
            "❂ <b>ЦИКЛ СДЕЛКИ:</b>",
            "╰ Сдача eSIM [24/7] ─ Отчёт ─ Расчет",
            "",
            "📊 <b>ВАШИ ПОКАЗАТЕЛИ:</b>",
            f"  ╰ ПРИНЯТО: <code>{approved}</code>",
            f"  ╰ В ОБРАБОТКЕ: <code>{pending + in_review}</code>",
            f"  ╰ ОТКЛОНЕНО (БРАК): <code>{rejected}</code>",
            "  │",
            f"  ╰ ВЫПЛАЧЕНО: {format_currency(float(payout) if payout is not None else 0)}",
            DIVIDER,
            "<i>Навигация по меню системы</i> ↴",
        ]
        return "\n".join(lines)


    def render_queue(self, submissions: Sequence[Any], *, title: str = "Буфер материала") -> str:
        lines: list[str] = [HEADER_QUEUE, DIVIDER, f"▪️ <b>{escape(title)}</b>"]
        if not submissions:
            lines.extend([" 🔲 <i>Буфер пуст</i>", DIVIDER])
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
        """Спецификация актива при аудите."""
        sid = self._pick(submission, "id", default="—")
        phone = self._pick(submission, "phone_normalized", "description_text", default="—")
        seller = self._pick(submission, "seller", default=None)
        seller_label = self._username_label(seller)
        
        category_obj = self._pick(submission, "category", default=None)
        category = escape(str(getattr(category_obj, "title", "Без кластера")))

        lines: list[str] = [
            f"{HEADER_ASSET} #<code>{sid}</code>",
            DIVIDER,
            f"◾️ <b>Линия связи:</b> {format_phone(str(phone))}",
            f"◾️ <b>Источник:</b> {seller_label}",
            f"◾️ <b>Категория:</b> {category}",
        ]
        if is_duplicate:
            lines.append("")
            lines.append(" ✕ <b>Внимание:</b> обнаружено дублирование в реестре.")
        
        lines.append(DIVIDER)
        return "\n".join(lines)

    def render_in_work_list(self, submissions: Sequence[Any]) -> str:
        lines: list[str] = [HEADER_INWORK, DIVIDER]
        if not submissions:
            lines.extend([" 🔲 <i>Активных сессий нет</i>", DIVIDER])
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
            f"{greeting}, <b>{safe_actor}</b>.",
            "Система функционирует в штатном режиме.",
            "",
            "<b>Состояние узлов:</b>",
            f" ⏳ Ожидают аудита: <code>{pending}</code>",
            f" 🔄 В работе (без статуса): <code>{in_review}</code>",
            f" ◾️ Выкуплено: <code>{approved}</code>{cycle_note}",
            f" ▫️ Отклонено: <code>{rejected}</code>{cycle_note}",
            DIVIDER,
        ])

    def render_inwork_hub(self, items: Sequence[Any], *, index_offset: int = 0, total: int | None = None) -> str:
        """Компактный список сессий в работе (Операционная зона)."""
        count = total if total is not None else len(items)
        lines: list[str] = [
            HEADER_INWORK,
            DIVIDER,
            f"<b>В работе:</b> <code>{count}</code>",
        ]

        if not items:
            lines.append("")
            lines.append(" ▫️ <i>Нет активных сессий</i>")
            lines.append(DIVIDER)
            return "\n".join(lines)

        lines.append("")

        for idx, item in enumerate(items, start=index_offset + 1):
            phone = self._pick(item, "description_text", "phone_normalized", default="—")
            phone_str = (str(phone) or "").strip() or "—"

            cat = self._pick(item, "category", default=None)
            cat_title = str(getattr(cat, "title", "")) if cat else ""
            cat_short = cat_title[:12] if cat_title else ""

            tag = f" <i>{escape(cat_short)}</i>" if cat_short else ""
            lines.append(f" {idx}. <code>{escape(phone_str[:20])}</code>{tag}")

        lines.append(DIVIDER)
        return "\n".join(lines)

    def render_inwork_sellers(
        self,
        seller_groups: Sequence[Mapping[str, Any]],
        *,
        total_sellers: int,
        total_cards: int,
    ) -> str:
        """Level 1: список поставщиков с количеством карточек."""
        lines: list[str] = [
            HEADER_INWORK,
            DIVIDER,
            f"<b>Поставщиков:</b> <code>{total_sellers}</code>  ·  "
            f"<b>Карточек:</b> <code>{total_cards}</code>",
        ]
        if not seller_groups:
            lines.extend(["", " ▫️ <i>Нет активных сессий</i>", DIVIDER])
            return "\n".join(lines)
        lines.append("")
        for idx, g in enumerate(seller_groups, 1):
            label = escape(str(g.get("label", "—")))
            count = int(g.get("count", 0))
            lines.append(f" {idx}. {label} — <code>{count}</code> шт.")
        lines.append(DIVIDER)
        return "\n".join(lines)

    def render_inwork_seller_cards(
        self,
        seller_label: str,
        items: Sequence[Any],
        *,
        total: int,
    ) -> str:
        """Level 2: карточки конкретного поставщика."""
        lines: list[str] = [
            HEADER_INWORK,
            DIVIDER,
            f"<b>Поставщик:</b> {escape(seller_label)}",
            f"<b>Карточек:</b> <code>{total}</code>",
        ]
        if not items:
            lines.extend(["", " ▫️ <i>Нет карточек</i>", DIVIDER])
            return "\n".join(lines)
        lines.append("")
        for idx, item in enumerate(items, 1):
            phone = self._pick(item, "description_text", "phone_normalized", default="—")
            phone_str = (str(phone) or "").strip() or "—"
            short = phone_str[-5:] if len(phone_str) > 5 else phone_str

            cat = self._pick(item, "category", default=None)
            cat_title = str(getattr(cat, "title", "")) if cat else ""
            cat_short = cat_title[:12] if cat_title else "—"

            hold_raw = getattr(item, "hold_assigned", None) or ""
            hold = "" if hold_raw.lower() == "no_hold" else hold_raw

            parts = [f"SIM: ..<code>{escape(short)}</code>", escape(cat_short)]
            if hold:
                parts.append(escape(str(hold)[:15]))

            lines.append(f" {idx}. " + " · ".join(parts))
        lines.append(DIVIDER)
        return "\n".join(lines)

    def render_inwork_search_prompt(self) -> str:
        return "\n".join([
            HEADER_INWORK,
            DIVIDER,
            "🔍 <b>Поиск по номеру</b>",
            "",
            "Введите минимум 3 цифры номера телефона",
            "или полный номер в формате +7XXXXXXXXXX.",
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
            lines.extend([" 🔲 <i>Транзакции отсутствуют</i>", DIVIDER])
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
        """Экран массовых выплат."""
        lines: list[str] = [HEADER_FINANCE, DIVIDER, f"<b>{escape(title)}</b>", ""]
        
        if not payouts:
            lines.extend([" ▫️ <i>Ордеры на распределение отсутствуют</i>", DIVIDER])
            return "\n".join(lines)

        total_amount = 0.0
        total_items = 0
        for payout in payouts:
            username = escape(str(self._pick(payout, "username", default="—")))
            accepted_count = int(self._pick(payout, "accepted_count", default=0) or 0)
            amount = float(self._pick(payout, "to_pay", "amount", default=0.0))
            
            total_amount += amount
            total_items += accepted_count
            lines.append(f" ◾️ {username} │ {accepted_count} шт. │ {format_currency(amount)}")

        lines.append(DIVIDER_LIGHT)
        lines.append(f" <b>Итоговая ликвидность:</b> {total_items} шт.")
        lines.append(f" <b>Сумма к списанию:</b> {format_currency(total_amount)}")
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
            lines.append(" 🔲 <i>Кластеры не сконфигурированы</i>")
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