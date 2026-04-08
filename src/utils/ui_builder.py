"""GDPX — дизайн-система интерфейса бота.

Все экраны отрисовываются в формате HTML (parse_mode='HTML').
Единая визуальная тема: "Monochrome Blocks". Брутальная геометрия,
крупные индикаторы, массивные разделители.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from datetime import datetime
from html import escape
from typing import Any

from src.keyboards.constants import (
    DIVIDER,
    DIVIDER_LIGHT,
    HEADER_ADMIN_MAIN,
    HEADER_CATCON,
    HEADER_FINANCE,
    HEADER_HISTORY,
    HEADER_MAIN,
    HEADER_OWNER_MAIN,
    HEADER_PROFILE,
    HEADER_QUEUE,
    HEADER_STATS,
    PREFIX_ITEM,
    PREFIX_LAST,
    STATUS_EMOJI,
)


def get_time_greeting() -> str:
    hour = datetime.now().hour
    if 6 <= hour < 12:
        return "Утренняя сессия"
    if 12 <= hour < 18:
        return "Дневная сессия"
    if 18 <= hour < 23:
        return "Вечерняя сессия"
    return "Ночная сессия"


def format_currency(amount: float) -> str:
    return f"<code>{float(amount):.2f}</code> USDT"


class GDPXRenderer:
    def _render_heartbeat(self) -> str:
        """Генерирует динамическую строку 'сердцебиения' системы."""
        latency = random.randint(12, 48)
        statuses = ["SECURE", "STABLE", "ENCRYPTED", "SYNCED"]
        status = random.choice(statuses)
        return f"📡 <code>[STATUS: {status} // PING: {latency}ms]</code>"

    def _get_agent_wisdom(self) -> str:
        """Возвращает случайную цитату или совет для агента."""
        wisdom = [
            "Качество — это единственная валюта, которая не обесценивается.",
            "Тишина в эфире — признак профессионализма.",
            "Система видит всё. Будь безупречен.",
            "Твой позывной — твоя честь. Береги её.",
            "Академия GDPX: Знания конвертируются в капитал.",
            "Чистый актив — залог долгого сотрудничества.",
        ]
        return f"<i>💡 {random.choice(wisdom)}</i>"

    def _render_terminal_logs(self, limit: int = 3) -> str:
        """Имитирует последние системные логи для атмосферы."""
        logs = [
            "Link established...",
            "Encryption keys rotated.",
            "Buffer cleared.",
            "Node synchronization complete.",
            "Uplink active.",
            "Database integrity verified.",
        ]
        selected = random.sample(logs, limit)
        return "\n".join([f"<code>> {log}</code>" for log in selected])

    def render_seller_profile_premium(
        self, user: Any, stats: Mapping[str, Any], recent_submissions: Sequence[Any]
    ) -> str:
        """Премиальный рендеринг профиля селлера (Silver Sakura)."""

        balance = float(user.pending_balance or 0)
        total_paid = float(user.total_paid or 0)
        approved = int(stats.get("approved_count", 0) or 0)
        username = user.nickname or user.pseudonym or user.username or str(user.telegram_id)
        if user.is_incognito:
            username = "🕶 INCOGNITO"

        greeting = get_time_greeting()
        rank_name, rank_emoji, rank_desc, next_target = self._rank_info(approved)
        progress_bar = self._rank_progress_bar(approved, next_target)

        # Значки достижений
        badges_str = " ".join(user.badges) if user.badges else "<i>достижений пока нет</i>"

        lines = [
            self._render_heartbeat(),
            HEADER_PROFILE,
            DIVIDER,
            f"👋 <b>{greeting}, {escape(username)}!</b>",
            f"🏅 <b>ДОСТИЖЕНИЯ:</b> {badges_str}",
            "",
            f"💰 <b>ТЕКУЩИЙ БАЛАНС:</b> <code>{balance:.2f}</code> USDT",
            f"📈 <b>ВСЕГО ВЫПЛАЧЕНО:</b> <code>{total_paid:.2f}</code> USDT",
            "",
            f"🛡 <b>РАНГ:</b> {rank_emoji} <code>{rank_name.upper()}</code>",
            f"📊 <b>ПРОГРЕСС:</b> [{progress_bar}]",
            f"🎁 <b>БОНУС:</b> <i>{rank_desc}</i>",
            DIVIDER_LIGHT,
            "📑 <b>ПОСЛЕДНИЕ АКТИВЫ:</b>",
        ]

        if not recent_submissions:
            lines.append("  <i>└ Пока нет проверенных активов.</i>")
        else:
            for i, s in enumerate(recent_submissions[:5]):
                status_icon = STATUS_EMOJI.get(s.status, "▫️")
                prefix = PREFIX_LAST if i == len(recent_submissions[:5]) - 1 else PREFIX_ITEM
                date_str = s.created_at.strftime("%d.%m %H:%M")
                # Упрощенная строка для компактности
                lines.append(f"{prefix} {status_icon} #{s.id} | {date_str} | <code>{s.status.upper()}</code>")

        lines.append(DIVIDER)
        lines.append(self._get_agent_wisdom())
        lines.append("<i>Выберите раздел управления ниже ↴</i>")
        return "\n".join(lines)

    def render_pin_pad(self, current_input: str, title: str = "SECURITY // PIN ACCESS") -> str:
        """Отрисовка экрана ввода PIN."""
        masked = "*" * len(current_input)
        return "\n".join(
            [
                self._render_heartbeat(),
                f"🛡 <b>{title}</b>",
                DIVIDER,
                "Для подтверждения доступа введите ваш персональный PIN-код.",
                "",
                f"ВВОД: <code>{masked if masked else '____'}</code>",
                DIVIDER,
                "<i>Забыли PIN? Свяжитесь с Архитектором.</i>",
            ]
        )

    def render_notification_settings(self, current_pref: str) -> str:
        """Отрисовка меню настроек уведомлений."""
        pref_labels = {
            "full": "ПОЛНЫЙ (о каждой проверке) ✅",
            "summary": "ИТОГОВЫЙ (раз в сутки) 📊",
            "none": "ВЫКЛЮЧЕНЫ ▫️",
        }
        return "\n".join(
            [
                self._render_heartbeat(),
                "🔔 <b>GDPX // NOTIFICATION CENTER</b>",
                DIVIDER,
                f"ТЕКУЩИЙ РЕЖИМ: <b>{pref_labels.get(current_pref, 'Неизвестно')}</b>",
                DIVIDER_LIGHT,
                "Выберите желаемый формат оповещений о проверке ваших активов.",
                DIVIDER,
                "<i>Настройки применяются мгновенно.</i>",
            ]
        )

    def render_seller_stats(self, period_label: str, stats: dict, rank_pos: tuple[int, int]) -> str:
        """Отрисовка детальной статистики за период."""
        pos, total = rank_pos
        quality = stats.get("quality", 100.0)

        return "\n".join(
            [
                self._render_heartbeat(),
                f"📈 <b>STATISTICS // [{period_label.upper()}]</b>",
                DIVIDER,
                f"🏆 <b>МЕСТО В РЕЙТИНГЕ:</b> <code>{pos}</code> из <code>{total}</code>",
                f"✨ <b>КАЧЕСТВО ТОВАРА:</b> <code>{quality:.1f}%</code>",
                DIVIDER_LIGHT,
                f"✅ <b>ЗАЧТЕНО:</b> <code>{stats.get('accepted', 0)}</code> шт.",
                f"❌ <b>БРАК (ОТКЛОНЕНО):</b> <code>{stats.get('rejected', 0)}</code> шт.",
                f"📦 <b>НЕ СКАН / ПОВТОР:</b> <code>{stats.get('not_scan', 0)}</code> шт.",
                f"🚫 <b>БЛОКИРОВКА:</b> <code>{stats.get('blocked', 0)}</code> шт.",
                DIVIDER_LIGHT,
                f"💰 <b>ВЫРУЧКА ЗА ПЕРИОД:</b> <code>{float(stats.get('earned', 0)):.2f}</code> USDT",
                DIVIDER,
                self._get_agent_wisdom(),
            ]
        )

    def render_seller_settings(self, user: Any) -> str:
        """Отрисовка меню настроек."""
        alias = user.nickname or user.pseudonym or "не установлен"
        incognito = "ВКЛЮЧЕН 🎭" if user.is_incognito else "ВЫКЛЮЧЕН ▫️"
        has_pin = "УСТАНОВЛЕН ✅" if user.pin_code else "НЕ УСТАНОВЛЕН ❌"

        return "\n".join(
            [
                self._render_heartbeat(),
                "⚙️ <b>GDPX // CONFIGURATION</b>",
                DIVIDER,
                f"👤 <b>ПСЕВДОНИМ:</b> <code>{escape(alias)}</code>",
                f"🎭 <b>РЕЖИМ INCOGNITO:</b> <code>{incognito}</code>",
                f"🛡 <b>ЗАЩИТА PIN-КОДОМ:</b> <code>{has_pin}</code>",
                DIVIDER_LIGHT,
                "<b>ДОСТУПНЫЕ ОПЦИИ:</b>",
                " ├ Безопасность и PIN-код",
                " ├ Смена публичного имени",
                " ├ Шаблоны загрузки активов",
                " └ Экспорт данных в Excel",
                DIVIDER,
                "<i>Выберите категорию для изменения ↴</i>",
            ]
        )

    def render_dashboard(self, stats: Mapping[str, Any]) -> str:
        # (Updated to use new constants)
        actor = str(stats.get("username") or "resident")
        greeting = get_time_greeting()
        return "\n".join(
            [
                self._render_heartbeat(),
                HEADER_MAIN,
                DIVIDER,
                f"👋 <b>Приветствуем, {escape(actor)}</b>",
                f"🕒 <code>{greeting}</code>, соединение установлено.",
                "",
                "❂ <b>ЭКОСИСТЕМА GDPX</b>",
                "╰ Мы учим - вы производите - мы забираем.",
                "<i>Стань системным партнером и зарабатывай на eSIM активах!</i>",
                "",
                "📊 <b>ТЕКУЩИЕ ПОКАЗАТЕЛИ:</b>",
                f" ├ ПРИНЯТО: <code>{int(stats.get('approved_count', 0))}</code>",
                f" ├ В ОБРАБОТКЕ: <code>{int(stats.get('pending_count', 0))}</code>",
                f" └ ВЫПЛАЧЕНО: {format_currency(float(stats.get('total_payout_amount', 0)))}",
                DIVIDER,
                self._get_agent_wisdom(),
                "",
                "<i>Выберите раздел системы:</i>",
            ]
        )

    @staticmethod
    def _rank_info(approved_count: int) -> tuple[str, str, str, int | None]:
        """Возвращает (Название, Эмодзи, Описание, Цель)."""
        if approved_count <= 50:
            return "Новичок", "🌱", "Только начинаешь путь", 51
        if approved_count <= 300:
            return "Поставщик", "📦", "+5% к ставке", 301
        if approved_count <= 1000:
            return "Вендор", "🏷️", "+10% к ставке + приоритет", 1001
        if approved_count <= 3000:
            return "Мастер", "🌸", "+15% к ставке + менеджер", 3001
        if approved_count <= 8000:
            return "Элита", "🏆", "+20% к ставке + авто-выплаты", 8001
        return "Легенда", "🌟", "+25% к ставке + эксклюзив", None

    @staticmethod
    def _rank_progress_bar(approved_count: int, next_target: int | None) -> str:
        total_cells = 12
        if next_target is None:
            return "▰" * total_cells

        # Для корректного отображения прогресса внутри текущего ранга
        ranges = [0, 51, 301, 1001, 3001, 8001]
        current_base = 0
        for r in ranges:
            if next_target > r:
                current_base = r
            else:
                break

        needed = next_target - current_base
        current_progress = approved_count - current_base

        ratio = min(max(current_progress / (needed or 1), 0), 1.0)
        filled = int(round(ratio * total_cells))
        return ("▰" * filled) + ("▱" * (total_cells - filled))

    def render_queue_lobby(self, *, pending_count: int) -> str:
        return "\n".join(
            [
                self._render_heartbeat(),
                HEADER_QUEUE,
                DIVIDER,
                f"🔲 <b>PENDING SYNC:</b> <code>{int(pending_count)}</code>",
                DIVIDER,
            ]
        )

    def render_owner_dashboard(self, stats: Mapping[str, Any]) -> str:
        """Эксклюзивный Командный Центр (Silver Sakura Premium)."""
        actor = str(stats.get("username") or "Owner")
        greeting = get_time_greeting()

        total_debt = float(stats.get("total_debt", 0))
        paid_today = float(stats.get("paid_today", 0))
        active_mods = int(stats.get("active_mods", 0))
        total_pending = int(stats.get("total_pending", 0))
        volume_24h = float(stats.get("volume_24h", 0))
        top_op = str(stats.get("top_operator", "N/A"))

        return "\n".join(
            [
                "🏯 <b>КОМАНДНЫЙ ЦЕНТР GDPX</b>",
                DIVIDER,
                f"👋 <b>{greeting}, {escape(actor)}</b>",
                f"<i>Система управления активами активна.</i>",
                self._render_heartbeat(),
                DIVIDER_LIGHT,
                "💰 <b>ФИНАНСОВЫЙ ОБОРОТ (24H):</b>",
                f" ├ Оборот: <code>{volume_24h:.2f}</code> USDT",
                f" ├ Выплачено: <code>{paid_today:.2f}</code> USDT",
                f" └ К выплате: <code>{total_debt:.2f}</code> USDT",
                DIVIDER_LIGHT,
                "🚀 <b>ОПЕРАЦИОННЫЙ СТАТУС:</b>",
                f" ├ В очереди: <code>{total_pending}</code> активов",
                f" ├ Модераторы: <code>{active_mods}</code> онлайн",
                f" └ Топ-сегмент: <code>{top_op}</code>",
                DIVIDER_LIGHT,
                "🏥 <b>СОСТОЯНИЕ СИСТЕМЫ:</b>",
                f" ├ Статус: 🟢 <code>HEALTHY</code>",
                f" └ Пинг: <code>{random.randint(12, 28)}ms</code>",
                DIVIDER,
                "<i>Выберите приоритетное направление ↴</i>",
            ]
        )

    def render_owner_finance(self, stats: Mapping[str, Any], pending_sellers: Sequence[Any]) -> str:
        """Раздел 'Выплаты и финансы' для владельца."""
        lines = [
            self._render_heartbeat(),
            HEADER_FINANCE,
            DIVIDER,
            "💰 <b>ВЫПЛАТЫ И ФИНАНСЫ</b>",
            DIVIDER_LIGHT,
            f"📅 <b>ИТОГИ ЗА 24H:</b> <code>{float(stats.get('paid_today', 0)):.2f}</code> USDT",
            f"🏦 <b>ОБЩАЯ ЗАДОЛЖЕННОСТЬ:</b> <code>{float(stats.get('total_debt', 0)):.2f}</code> USDT",
            DIVIDER_LIGHT,
            "📑 <b>ТОП ОЖИДАЮЩИХ ВЫПЛАТ:</b>",
        ]

        if not pending_sellers:
            lines.append(" └ Ожидающих выплат нет.")
        else:
            for s in pending_sellers[:10]:
                username = s.username or str(s.telegram_id)
                balance = float(s.pending_balance)
                lines.append(f" ├ {username}: <code>{balance:.2f}</code> USDT")

        lines.extend([DIVIDER, "<i>Используйте кнопки для проведения выплат и просмотра истории ↴</i>"])
        return "\n".join(lines)

    def render_platform_analytics(self, stats: dict) -> str:
        """Отрисовка общей аналитики платформы."""
        return "\n".join(
            [
                self._render_heartbeat(),
                HEADER_STATS,
                DIVIDER,
                "📈 <b>ОБЩАЯ АНАЛИТИКА ПЛАТФОРМЫ</b>",
                DIVIDER_LIGHT,
                f"📦 Всего активов: <code>{stats['total_count']}</code>",
                f"✅ Принято: <code>{stats['accepted_count']}</code>",
                f"❌ Отклонено: <code>{stats['rejected_count']}</code>",
                f"✨ Процент брака: <code>{stats['reject_rate']:.1f}%</code>",
                f"💰 Средняя ставка: <code>{stats['avg_rate']:.2f}</code> USDT",
                DIVIDER,
                "<i>Данные за всё время работы системы.</i>",
            ]
        )

    def render_moderators_stats(self, mods: list[dict]) -> str:
        """Отрисовка статистики по модераторам."""
        lines = [
            self._render_heartbeat(),
            HEADER_STATS,
            DIVIDER,
            "👥 <b>ЭФФЕКТИВНОСТЬ МОДЕРАТОРОВ</b>",
            DIVIDER_LIGHT,
        ]
        if not mods:
            lines.append("<i>Данных о работе модераторов пока нет.</i>")
        else:
            for m in mods[:10]:
                lines.append(
                    f"👤 {m['username']}: <code>{m['total']}</code> шт. | <code>{m['accept_rate']:.1f}%</code> OK"
                )

        lines.append(DIVIDER)
        return "\n".join(lines)

    def render_sellers_leaderboard_owner(self, sellers: list[dict]) -> str:
        """Отрисовка рейтинга селлеров для владельца."""
        lines = [
            self._render_heartbeat(),
            HEADER_STATS,
            DIVIDER,
            "💰 <b>РЕЙТИНГ СЕЛЛЕРОВ (VOLUME)</b>",
            DIVIDER_LIGHT,
        ]
        if not sellers:
            lines.append("<i>Продавцов в системе пока нет.</i>")
        else:
            for i, s in enumerate(sellers[:10], 1):
                lines.append(
                    f"{i}. {s['username']}: <code>{s['total']}</code> шт. | <code>{s['earned']:.2f}</code> USDT"
                )

        lines.append(DIVIDER)
        return "\n".join(lines)

    def render_cat_constructor_step(self, step: int, total_steps: int, title: str, description: str) -> str:
        """Отрисовка шагов конструктора категорий (eSIM)."""
        return "\n".join(
            [
                self._render_heartbeat(),
                HEADER_CATCON,
                DIVIDER,
                f"🛠 <b>STAGE {step}/{total_steps} | {escape(title)}</b>",
                "",
                escape(description),
                DIVIDER_LIGHT,
            ]
        )

    def render_cat_constructor_confirm(self, operator: str, sim_type: str, price: str) -> str:
        """Отрисовка финального шага (подтверждение) конструктора категорий."""
        return "\n".join(
            [
                self._render_heartbeat(),
                HEADER_CATCON,
                DIVIDER,
                "🛠 <b>STAGE 4/4 | CONFIRMATION</b>",
                "",
                "<b>Проверьте параметры нового кластера:</b>",
                f" ├ <b>Operator:</b> <code>{escape(operator)}</code>",
                f" ├ <b>Architecture:</b> <code>{escape(sim_type)}</code>",
                f" └ <b>Rate:</b> <code>{escape(price)}</code> USDT",
                DIVIDER_LIGHT,
                "<i>Подтвердите интеграцию в базу данных</i> ↴",
            ]
        )

    def render_category_manage(self, category: Any) -> str:
        """Отрисовка карточки управления категорией (кластером)."""
        from html import escape

        priority = "🏮 PRIORITY" if getattr(category, "is_priority", False) else "▫️ STANDARD"
        status = "🟢 ACTIVE" if category.is_active else "🔴 DISABLED"

        return "\n".join(
            [
                self._render_heartbeat(),
                HEADER_CATCON,
                DIVIDER,
                f"🗂 <b>CLUSTER:</b> <code>{escape(category.title)}</code>",
                DIVIDER_LIGHT,
                f" ├ <b>ID:</b> <code>{category.id}</code>",
                f" ├ <b>Status:</b> {status}",
                f" ├ <b>Access:</b> {priority}",
                f" └ <b>Rate:</b> <code>{category.payout_rate}</code> USDT",
                DIVIDER_LIGHT,
                "Выберите действие для управления:",
            ]
        )
