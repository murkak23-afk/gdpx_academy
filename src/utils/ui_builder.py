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
    HEADER_LEADERBOARD,
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
            "Академия GDPX: Высший пилотаж в мире цифровых активов.",
            "Академия GDPX: Искусство быть первым в невидимом поле.",
            "Академия GDPX: Твой результат - лучшая рекомендация.",
            "Академия GDPX: Алгоритм успеха прописан в твоих действиях.",
            "Академия GDPX: Знания конвертируются в капитал.",
            "Академия GDPX: Качественная симка - залог долгого сотрудничества.",
            "Академия GDPX: Твой результат - лучшая рекомендация."
            "Академия GDPX: Точность в расчетах, твердость в решениях."
            "Академия GDPX: Гроссмейстеры в мире eSIM."
            "Академия GDPX: Когда технология переходит в искусство."
            "Академия GDPX: Ничего личного. Только безупречный ворк."
            "Академия GDPX: Твой интеллект - твой печатный станок."
            "Академия GDPX: Прокладывай путь там, где другие ищут выход."
            "Академия GDPX: Мастерство в тени, профит на свету."

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
            f"🥋 <b>РАНГ:</b> {rank_emoji} <code>{rank_name.upper()}</code>",
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

    def render_seller_stats(self, period_label: str, stats: Mapping[str, Any], rank_pos: tuple[int, int]) -> str:
        """Отрисовка детальной статистики селлера."""
        
        accepted = int(stats.get("accepted", 0))
        rejected = int(stats.get("rejected", 0))
        blocked = int(stats.get("blocked", 0))
        not_scan = int(stats.get("not_scan", 0))
        earned = float(stats.get("earned", 0))
        quality = float(stats.get("quality", 100.0))
        
        current_rank, total_ranks = rank_pos
        
        lines = [
            self._render_heartbeat(),
            HEADER_STATS,
            DIVIDER,
            f"📊 <b>СТАТИСТИКА: {period_label.upper()}</b>",
            DIVIDER_LIGHT,
            f"✅ <b>ПРИНЯТО:</b> <code>{accepted}</code> шт.",
            f"❌ <b>ОТКЛОНЕНО:</b> <code>{rejected}</code> шт.",
            f"🚫 <b>ЗАБЛОКИРОВАНО:</b> <code>{blocked}</code> шт.",
            f"⚠️ <b>НЕ СКАН:</b> <code>{not_scan}</code> шт.",
            DIVIDER_LIGHT,
            f"💰 <b>ЗАРАБОТАНО:</b> <code>{earned:.2f}</code> USDT",
            f"✨ <b>КАЧЕСТВО:</b> <code>{quality:.1f}%</code>",
            f"🏆 <b>РЕЙТИНГ:</b> <code>{current_rank}</code> из <code>{total_ranks}</code>",
            DIVIDER,
            "<i>Выберите период для фильтрации ↴</i>"
        ]
        return "\n".join(lines)

    def render_seller_settings(self, user: Any) -> str:
        """Отрисовка меню настроек."""
        alias = user.nickname or user.pseudonym or "не установлен"
        incognito = "ВКЛЮЧЕН 🎭" if user.is_incognito else "ВЫКЛЮЧЕН ▫️"

        return "\n".join(
            [
                self._render_heartbeat(),
                "⚙️ <b>GDPX // CONFIGURATION</b>",
                DIVIDER,
                f"👤 <b>ПСЕВДОНИМ:</b> <code>{escape(alias)}</code>",
                f"🎭 <b>РЕЖИМ INCOGNITO:</b> <code>{incognito}</code>",
                DIVIDER_LIGHT,
                "<b>ДОСТУПНЫЕ ОПЦИИ:</b>",
                " ├ Смена публичного имени",
                " ├ Шаблоны загрузки активов",
                " └ Экспорт данных в Excel",
                DIVIDER,
                "<i>Выберите категорию для изменения ↴</i>",
            ]
        )

    def render_personal_data(self, user: Any, stats: Mapping[str, Any]) -> str:
        """Отрисовка экрана личных данных пользователя."""
        created_at = user.created_at.strftime("%d.%m.%Y")
        username = user.username or "не привязан"
        
        return "\n".join([
            self._render_heartbeat(),
            "👤 <b>GDPX // PERSONAL DATA</b>",
            DIVIDER,
            f"🆔 <b>SYSTEM ID:</b> <code>{user.id}</code>",
            f"📡 <b>TELEGRAM ID:</b> <code>{user.telegram_id}</code>",
            f"🔗 <b>USERNAME:</b> @{escape(username)}",
            f"📅 <b>РЕГИСТРАЦИЯ:</b> <code>{created_at}</code>",
            DIVIDER_LIGHT,
            "📊 <b>ОБЩАЯ СТАТИСТИКА:</b>",
            f" ├ Всего загружено: <code>{int(stats.get('accepted', 0) + stats.get('rejected', 0) + stats.get('pending', 0))}</code>",
            f" ├ Зачтено: <code>{int(stats.get('accepted', 0))}</code>",
            f" └ Отклонено: <code>{int(stats.get('rejected', 0))}</code>",
            DIVIDER_LIGHT,
            f"💰 <b>ТЕКУЩИЙ БАЛАНС:</b> <code>{float(user.pending_balance or 0):.2f}</code> USDT",
            DIVIDER,
            "<i>Эти данные используются для внутренней идентификации.</i>"
        ])

    def render_dashboard(self, stats: Mapping[str, Any]) -> str:
        # (Updated to use new constants)
        actor = str(stats.get("username") or "resident")
        greeting = get_time_greeting()
        return "\n".join(
            [
                HEADER_MAIN,
                DIVIDER,
                f"👋 <b>Приветствуем, {escape(actor)}</b>",
                f"🕒 <code>{greeting}</code>, соединение установлено.",
                "",
                "❂ <b>ЭКОСИСТЕМА GDPX</b>",
                "╰ Мы учим - вы производите - мы забираем.",
                "<i>Интегрируйся в систему - монетизируй eSIM технологии.</i>",
                "",
                "📊 <b>ТЕКУЩИЕ ПОКАЗАТЕЛИ:</b>",
                f" ├ ПРИНЯТО: <code>{int(stats.get('approved_count', 0))}</code>",
                f" ├ В ОБРАБОТКЕ: <code>{int(stats.get('pending_count', 0))}</code>",
                f" └ ВЫПЛАЧЕНО: {format_currency(float(stats.get('total_payout_amount', 0)))}",
                DIVIDER,
                "",
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
            return "Поставщик", "📦", "", 301
        if approved_count <= 1000:
            return "Вендор", "🏷️", "", 1001
        if approved_count <= 3000:
            return "Мастер", "🌸", "", 3001
        if approved_count <= 8000:
            return "Элита", "🏆", "", 8001
        return "Легенда", "🌟", "", None

    @staticmethod
    def _rank_progress_bar(approved_count: int, next_target: int | None) -> str:
        total_cells = 12
        if next_target is None:
            return "■" * total_cells

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
        return ("■" * filled) + ("□" * (total_cells - filled))

    def render_queue_lobby(self, *, pending_count: int, in_work_count: int) -> str:
        return "\n".join(
            [
                self._render_heartbeat(),
                HEADER_QUEUE,
                DIVIDER,
                f"🔲 <b>PENDING (ОЧЕРЕДЬ):</b> <code>{int(pending_count)}</code>",
                f"📟 <b>SCANNING (НА СКАНЕ):</b> <code>{int(in_work_count)}</code>",
                DIVIDER,
                "<i>Модератор берет активы, которые УЖЕ выданы на скан.</i>"
            ]
        )

    def render_owner_dashboard(self, stats: Mapping[str, Any]) -> str:
        """Эксклюзивный Командный Центр (Silver Sakura Premium)."""
        actor = str(stats.get("username") or "Owner")
        greeting = get_time_greeting()

        total_debt = float(stats.get("total_debt", 0))
        paid_today = float(stats.get("paid_today", 0))
        active_mods = int(stats.get("active_mods", 0))
        warehouse = int(stats.get("warehouse", 0))
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
                f" ├ На складе: <code>{warehouse}</code> активов",
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

    def render_finance_audit(self, stats: dict) -> str:
        """Отрисовка детального финансового аудита."""
        return "\n".join(
            [
                self._render_heartbeat(),
                HEADER_FINANCE,
                DIVIDER,
                "🛡️ <b>ФИНАНСОВЫЙ АУДИТ СИСТЕМЫ</b>",
                DIVIDER_LIGHT,
                f"🏦 <b>ОБЩЕЕ К ВЫПЛАТЕ:</b> <code>{float(stats.get('total_debt', 0)):.2f}</code> USDT",
                f"💎 <b>ВСЕГО ВЫПЛАЧЕНО:</b> <code>{float(stats.get('total_paid_all_time', 0)):.2f}</code> USDT",
                DIVIDER_LIGHT,
                f"📅 <b>ВЫПЛАТЫ (24H):</b> <code>{float(stats.get('paid_today', 0)):.2f}</code> USDT",
                f"📅 <b>ВЫПЛАТЫ (7D):</b> <code>{float(stats.get('paid_week', 0)):.2f}</code> USDT",
                f"📅 <b>ВЫПЛАТЫ (30D):</b> <code>{float(stats.get('paid_month', 0)):.2f}</code> USDT",
                DIVIDER_LIGHT,
                f"📈 <b>ОБОРОТ (30D):</b> <code>{float(stats.get('volume_30d', 0)):.2f}</code> USDT",
                DIVIDER,
                "<i>Все данные рассчитаны на основе транзакций и проверенных активов.</i>",
            ]
        )

    def render_moderation_audit(self, actions: list[dict], title: str = "АУДИТ ДЕЙСТВИЙ") -> str:
        """Отрисовка списка действий модерации."""
        lines = [
            self._render_heartbeat(),
            HEADER_HISTORY,
            DIVIDER,
            f"📜 <b>{title}</b>",
            DIVIDER_LIGHT,
        ]

        if not actions:
            lines.append(" └ <i>Действий не найдено.</i>")
        else:
            for a in actions:
                time_str = a["time"].strftime("%d.%m %H:%M")
                status = a["to_status"].value.upper()
                phone = a["phone"] or f"#{a['sub_id']}"
                line = f" ├ <code>[{time_str}]</code> <b>@{a['admin']}</b> → {phone} | <code>{status}</code>"
                if a.get("reason"):
                    line += f"\n   └ <i>Причина: {a['reason']}</i>"
                lines.append(line)

        lines.extend([DIVIDER, "<i>Последние действия системы.</i>"])
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

    def render_premium_leaderboard(self, top_sellers: list[dict], period_label: str) -> str:
        """Премиальная отрисовка доски лидеров в академическом стиле."""
        lines = [
            "🏆 <b>GDPX // ДОСКА ЛИДЕРОВ</b>",
            f"\n📅 <b>Период:</b> {period_label}",
            "\n────────────────────────────"
        ]

        if not top_sellers:
            lines.append("\n<i>В данном цикле трафик пока не зафиксирован.</i>")
        else:
            for i, s in enumerate(top_sellers, 1):
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "  "
                rank = f"{i:>2}."
                
                # Имя: добавляем @ если это username и нет других префиксов
                name = s['name']
                if not name.startswith(('@', 'ID:')):
                    name = f"@{name}"
                
                if len(name) > 14:
                    name = name[:12] + ".."
                name = name.ljust(14)
                
                earned = f"{int(s['earned']):,}".replace(",", " ")
                earned_str = f"{earned:>6} USDT"
                
                count = s['count']
                # Склонение
                if 11 <= count % 100 <= 14:
                    suffix = "симок"
                else:
                    rem = count % 10
                    if rem == 1: suffix = "симка"
                    elif 2 <= rem <= 4: suffix = "симки"
                    else: suffix = "симок"
                
                line = f"<code>{medal} {rank} {name} {earned_str}  • {count:>2} {suffix}</code>"
                lines.append(line)

        lines.append("────────────────────────────")
        lines.append(f"🕒 <b>Обновлено:</b> {datetime.now().strftime('%H:%M')} МСК")
        
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
