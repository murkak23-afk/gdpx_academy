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

# ─── Визуальные константы (Premium / Terminal Style) ───────────────────
HEADER_MAIN = "❖ <b>GDPX // ACADEMY</b>  ─ Terminal v2.5" 
HEADER_ADMIN_MAIN = "❖ <b>GDPX // ACADEMY</b> ─ ADMIN PANEL"
HEADER_FINANCE = "❖ <b>GDPX // ACADEMY</b> ─ FINANCE"
HEADER_PROFILE = "🀄️ <b>GDPX // ПРОФИЛЬ АГЕНТА</b>"
HEADER_QUEUE = "❖ <b>GDPX // ACADEMY</b> ─ DEFECTATION BUFFER"
HEADER_INWORK = "❖ <b>GDPX // ACADEMY</b> ─ OPERATION ZONE"
HEADER_SEARCH = "❖ <b>GDPX // ACADEMY</b> ─ GLOBAL SEARCH"
HEADER_CATCON = "❖ <b>GDPX // ACADEMY</b> ─ CONFIGURATION"
HEADER_ASSET = "❖ <b>GDPX // ACADEMY</b> ─ ASSET"

DIVIDER = "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰"
DIVIDER_LIGHT = "▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱"
PREFIX_ITEM = "└"

STATUS_EMOJI: dict[str, str] = {
    "accepted": "🟢",
    "approved": "🟢",
    "paid": "🟢",
    "rejected": "🔴",
    "cancelled": "▫️",
    "blocked": "🔴",
    "not_a_scan": "🔴",
    "pending": "⏳",
    "in_review": "🟠",
}

def format_phone(phone: str) -> str:
    normalized = (phone or "").strip() or "—"
    if normalized.isdigit() and len(normalized) == 11 and normalized.startswith("79"):
        local = normalized[1:]
        pretty = f"+7 ({local[:3]}) {local[3:6]}-{local[6:8]}-{local[8:10]}"
        return f"<code>{escape(pretty)}</code>"
    return f"<code>{escape(normalized)}</code>"

def format_currency(amount: float) -> str:
    return f"<code>{float(amount):.2f}</code> USDT"

def get_time_greeting() -> str:
    hour = datetime.now().hour
    if 6 <= hour < 12: return "Утренняя сессия"
    if 12 <= hour < 18: return "Дневная сессия"
    if 18 <= hour < 23: return "Вечерняя сессия"
    return "Ночная сессия"

def _status_emoji(status: Any) -> str:
    value = str(status).strip().lower()
    return STATUS_EMOJI.get(value, "▪️")

class GDPXRenderer:

    def render_user_profile(self, user_stats: Mapping[str, Any], user_id: int) -> str:
        """Отрисовка личного кабинета по новому шаблону."""

        approved = int(user_stats.get("approved_count") or 0)
        pending = int(user_stats.get("pending_count") or 0)
        rejected = int(user_stats.get("rejected_count") or 0)
        username = str(user_stats.get("username") or "resident")
        
        rank_label, next_target = self._rank_info(approved)
        
        # Расчет прогресса
        if next_target:
            percentage = int((approved / next_target) * 100)
            remaining = next_target - approved
        else:
            percentage = 100
            remaining = 0
            
        progress_bar = self._rank_progress_bar(approved, next_target)
        
        return "\n".join([
            HEADER_PROFILE,
            DIVIDER,
            f"🥋 Псевдоним: <code>{escape(username)}</code>",
            f"╰┈➤ Уровень доступа: [<b>{rank_label}</b>]",
            "",
            "- Дисциплина - мать победы!",
            "",
            "❋ <b>ПРОДУКТИВНОСТЬ:</b>",
            f"└ Успешно выкуплено: <code>{approved}</code>",
            f"└ В процессе оценки: <code>{pending}</code>",
            f"└ Отклонено (брак): <code>{rejected}</code>",
            "",
            f"❖ <b>ПРОГРЕСС:</b> [{progress_bar}] {percentage}%",
            (
                f" └➤ ДО АПГРЕЙДА: <code>{remaining}.00</code> USDT" # Используем USDT как визуальный юнит
                if next_target else " └➤ Максимальный статус достигнут."
            ),
            DIVIDER,
        ])

    def render_dashboard(self, stats: Mapping[str, Any]) -> str:
        approved = int(stats.get("approved_count", 0) or 0)
        pending = int(stats.get("pending_count", 0) or 0)
        rejected = int(stats.get("rejected_count", 0) or 0)
        payout = stats.get("total_payout_amount")
        actor = str(stats.get("username") or "resident")
        
        greeting = get_time_greeting()
        return "\n".join([
            HEADER_MAIN,
            DIVIDER,
            f"🃏 <b>CEЛЛЕР:</b> <code>{escape(actor)}</code>",
            "▫️ <b>СТАТУС:</b> <code>АКТИВЕН</code>",
            "",
            f"{greeting}, cоединение установлено.",
            "",
            "Добро пожаловать в закрытый контур Академии.",
            "",
            "❂ <b>ЭКОСИСТЕМА GDPX:</b>",
            "╰ Мы даём знания - вы производите актив - мы забираем весь объём.",
            "",
            "📊 <b>ВАШИ ПОКАЗАТЕЛИ:</b>",
            f"  ╰ ПРИНЯТО: <code>{approved}</code>",
            f"  ╰ В ОБРАБОТКЕ: <code>{pending}</code>",
            f"  ╰ ОТКЛОНЕНО (БРАК): <code>{rejected}</code>",
            "  │",
            f"  ╰ ВЫПЛАЧЕНО: {format_currency(float(payout) if payout is not None else 0)}",
            DIVIDER,
            "<i>Навигация по меню системы</i> ↴",
        ])

    @staticmethod
    def _rank_info(approved_count: int) -> tuple[str, int | None]:
        if approved_count < 10: return "РЕКРУТ", 10
        if approved_count < 50: return "АГЕНТ", 50
        if approved_count < 200: return "ВЕНДОР", 200
        return "ЭКСКЛЮЗИВ", None

    @staticmethod
    def _rank_progress_bar(approved_count: int, next_target: int | None) -> str:
        total_cells = 12 # Как в вашем примере
        if not next_target: return "▰" * total_cells
        
        ratio = min(approved_count / next_target, 1.0)
        filled = int(round(ratio * total_cells))
        return ("▰" * filled) + ("▱" * (total_cells - filled))

    def render_queue_lobby(self, *, pending_count: int) -> str:
        return "\n".join([
            HEADER_QUEUE,
            DIVIDER,
            f"🔲 <b>Ожидает синхронизации:</b> <code>{int(pending_count)}</code>",
            DIVIDER,
        ])

    def render_admin_dashboard(self, stats: Mapping[str, Any]) -> str:
        pending = int(stats.get("pending_count", 0) or 0)
        in_review = int(stats.get("in_review_count", 0) or 0)
        approved = int(stats.get("approved_count", 0) or 0)
        rejected = int(stats.get("rejected_count", 0) or 0)
        actor = str(stats.get("username") or "admin")
        
        greeting = get_time_greeting()
        return "\n".join([
            HEADER_ADMIN_MAIN,
            DIVIDER,
            f"👤 <b>Администратор:</b> {escape(actor)}",
            f"📅 <b>{greeting}</b>",
            DIVIDER_LIGHT,
            "<b>СОСТОЯНИЕ СИСТЕМЫ:</b>",
            f" ⏳ Ожидают: <code>{pending}</code> шт.",
            f" 🟠 В работе: <code>{in_review}</code> шт.",
            f" 🟢 Выкуплено: <code>{approved}</code> шт.",
            f" 🔴 Брак/Блок: <code>{rejected}</code> шт.",
            DIVIDER,
            "<i>Выберите раздел для управления:</i>"
        ])
    


    def render_cat_constructor_step(self, step: int, total_steps: int, title: str, description: str) -> str:
        """Отрисовка шагов конструктора категорий (eSIM)."""
        return "\n".join([
            HEADER_CATCON,
            DIVIDER,
            f"🛠 <b>ШАГ {step}/{total_steps} | {escape(title)}</b>",
            "",
            escape(description),
            DIVIDER_LIGHT,
        ])




    def render_cat_constructor_confirm(self, operator: str, sim_type: str, price: str) -> str:
        """Отрисовка финального шага (подтверждение) конструктора категорий."""
        return "\n".join([
            HEADER_CATCON,
            DIVIDER,
            "🛠 <b>ШАГ 4/4 | ПОДТВЕРЖДЕНИЕ</b>",
            "",
            "<b>Проверьте параметры нового кластера:</b>",
            f" ├ <b>Оператор:</b> <code>{escape(operator)}</code>",
            f" ├ <b>Тип (архитектура):</b> <code>{escape(sim_type)}</code>",
            f" └ <b>Ставка (ликвидность):</b> <code>{escape(price)}</code> USDT",
            DIVIDER_LIGHT,
            "<i>Подтвердите интеграцию в базу данных</i> ↴",
        ])
    


    def render_category_manage(self, category: Any) -> str:
            """Отрисовка карточки управления категорией (кластером)."""
            from html import escape
            priority = "🏮 ПРИОРИТЕТ" if getattr(category, "is_priority", False) else "▫️ ОБЫЧНЫЙ"
            status = "🟢 АКТИВЕН" if category.is_active else "🔴 ОТКЛЮЧЕН"
             
            return "\n".join([
                HEADER_CATCON,
                DIVIDER,
               f"🗂 <b>КЛАСТЕР:</b> <code>{escape(category.title)}</code>",
               DIVIDER_LIGHT,
               f" ├ <b>ID:</b> <code>{category.id}</code>",
              f" ├ <b>Статус:</b> {status}",
               f" ├ <b>Уровень:</b> {priority}",
               f" └ <b>Ставка:</b> <code>{category.payout_rate}</code> USDT",
               DIVIDER_LIGHT,
               "Выберите действие для управления:"
           ])
