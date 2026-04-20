"""GDPX — дизайн-система интерфейса бота.

Все экраны отрисовываются в формате HTML (parse_mode='HTML').
Единая визуальная тема: "Monochrome Blocks". Брутальная геометрия,
крупные индикаторы, массивные разделители.
"""

from __future__ import annotations

from decimal import Decimal
import random
from collections.abc import Mapping, Sequence
from datetime import datetime
from html import escape
from typing import Any
from src.core.constants import DIVIDER, DIVIDER_LIGHT

from src.presentation.common.constants import (
    HEADER_CATCON,
    HEADER_FINANCE,
    HEADER_HISTORY,
    HEADER_MAIN,
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
    def _get_agent_wisdom(self) -> str:
        """Возвращает случайную цитату или совет для агента."""
        wisdom = [
            "Академия GDPX: Высший пилотаж в мире цифровых активов.",
            "Академия GDPX: Искусство быть первым в невидимом поле.",
            "Академия GDPX: Твой результат - лучшая рекомендация.",
            "Академия GDPX: Алгоритм успеха прописан в твоих действиях.",
            "Академия GDPX: Знания конвертируются в капитал.",
            "Академия GDPX: Качественная симка - залог долгого сотрудничества.",
            "Академия GDPX: Точность в расчетах, твердость в решениях.",
            "Академия GDPX: Гроссмейстеры в мире eSIM.",
            "Академия GDPX: Когда технология переходит в искусство.",
            "Академия GDPX: Ничего личного. Только безупречный ворк.",
            "Академия GDPX: Твой интеллект - твой печатный станок.",
            "Академия GDPX: Прокладывай путь там, где другие ищут выход.",
            "Академия GDPX: Мастерство в тени, профит на свету."
        ]
        return f"<i>💡 {random.choice(wisdom)}</i>"

    def render_seller_profile_premium(
        self, user: Any, stats: Mapping[str, Any], recent_submissions: Sequence[Any]
    ) -> str:
        """Премиальный рендеринг профиля селлера (Silver Sakura)."""

        balance = float(user.pending_balance or 0)
        total_paid = float(user.total_paid or 0)
        approved = int(stats.get("accepted") or stats.get("approved_count", 0) or 0)
        username = user.nickname or user.pseudonym or user.username or str(user.telegram_id)
        if user.is_incognito:
            username = "🕶 INCOGNITO"

        greeting = get_time_greeting()
        
        # Ранговая система
        rank_lines = self._render_rank_section(approved)

        # Значки достижений
        badges_str = " ".join(user.badges) if user.badges else "пусто."

        lines = [
            "❖ <b>GDPX // ЛИЧНЫЙ ПРОФИЛЬ</b>",
            DIVIDER,
            f"👋 <b>{greeting}, {escape(username)}!</b>",
            f"🏅 <b>ДОСТИЖЕНИЯ:</b> {badges_str}",
            "",
            f"💰 <b>К ВЫПЛАТЕ:</b> <code>{balance:.2f}</code> USDT",
            f"📈 <b>ВСЕГО ВЫПЛАЧЕНО:</b> <code>{total_paid:.2f}</code> USDT",
            "",
            *rank_lines,
            DIVIDER_LIGHT,
            "📑 <b>ПОСЛЕДНИЕ АКТИВЫ:</b>",
        ]

        if not recent_submissions:
            lines.append("  <i>└ Пока нет проверенных активов.</i>")
        else:
            for i, s in enumerate(recent_submissions[:5]):
                status_icon = STATUS_EMOJI.get(s.status, "▫️")
                prefix = " ╰ " if i == len(recent_submissions[:5]) - 1 else " ┝ "
                date_str = s.created_at.strftime("%d.%m %H:%M")
                
                # Замена PENDING на СКЛАД
                status_display = s.status.upper()
                if status_display == "PENDING":
                    status_display = "СКЛАД"
                
                lines.append(f"{prefix}{status_icon} #{s.id} | {date_str} | {status_display}")

        lines.append(DIVIDER_LIGHT)
        lines.append(self._get_agent_wisdom())
        lines.append("<i>Выберите раздел управления ниже ↴</i>")
        return "\n".join(lines)

    def _render_rank_section(self, approved_count: int) -> list[str]:
        """Система рангов."""
        from src.domain.users.rank_service import RANKS
        
        current_idx = 0
        for i, rank in enumerate(RANKS):
            if approved_count >= rank.threshold:
                current_idx = i
            else:
                break
        
        current_rank = RANKS[current_idx]
        c_emoji, c_name, c_bonus_val = current_rank.emoji, current_rank.name, current_rank.bonus_percent
        c_bonus = f"+{c_bonus_val}% к выплатам" if c_bonus_val > 0 else "базовая ставка"
        
        if current_idx < len(RANKS) - 1:
            next_rank = RANKS[current_idx + 1]
            prev_threshold = current_rank.threshold
            next_threshold = next_rank.threshold
            
            total_needed = next_threshold - prev_threshold
            current_progress = approved_count - prev_threshold
            percent = int((current_progress / (total_needed or 1)) * 100)
            percent = min(max(percent, 0), 100)
            
            filled = int(percent / 10)
            bar = "▰" * filled + "▱" * (10 - filled)
            
            progress_line = f"📈 ПРОГРЕСС: 〚 {bar} 〛 {percent}%"
            rank_header = f"{c_emoji} <b>РАНГ:</b> <code>{c_name.upper()}</code> [ {approved_count}/{next_threshold} ]"
        else:
            progress_line = "📈 ПРОГРЕСС: 〚 ▰▰▰▰▰▰▰▰▰▰ 〛 100%"
            rank_header = f"{c_emoji} <b>РАНГ:</b> <code>{c_name.upper()}</code> [ MAX ]"

        # Возвращаем в новом компактном порядке
        return [
            rank_header,
            progress_line,
            f"💰 <b>БОНУС:</b> <i>{c_bonus}</i>"
        ]

    def render_sim_dynamics(self, submissions: Sequence[Any], total_counts: dict[str, int] = None) -> str:
        """Отрисовка динамики состояния eSIM (GDPX Terminal ERP Style)."""
        now = datetime.now()
        now_time = now.strftime("%H:%M")
        
        # 1. Заголовок
        lines = [
            "❖ <b>GDPX // ДИНАМИКА СИМ</b>",
            DIVIDER,
            ""
        ]

        # 2. Метрики (на основе всех данных)
        counts = total_counts or {}
        accepted = counts.get("accepted", 0)
        rejected = counts.get("rejected", 0)
        blocked = counts.get("blocked", 0)
        not_scan = counts.get("not_a_scan", 0)
        
        processed = accepted + rejected + blocked + not_scan
        total_flow = sum(counts.values())
        
        success_rate = (accepted / processed * 100) if processed > 0 else 100
        
        # Оценка выплаты
        avg_rate = 0.0
        if submissions:
            rates = [float(s.fixed_payout_rate or 0) for s in submissions if s.fixed_payout_rate]
            if rates: avg_rate = sum(rates) / len(rates)
        
        total_payout_est = avg_rate * accepted

        lines.extend([
            "📊 <b>КЛЮЧЕВЫЕ МЕТРИКИ:</b>",
            f" ├ Поток за сегодня: <code>{total_flow} шт.</code>",
            f" ├ Процент успеха: <code>{success_rate:.1f}%</code> ({accepted} из {processed})",
            f" └ Ожидаемая выплата: <code>~{total_payout_est:.2f} USDT</code>",
            ""
        ])

        # 3. Контур ожидания (Pipeline) - ВЕРТИКАЛЬНЫЙ для красоты и во избежание переносов
        pending = counts.get("pending", 0)
        in_work = counts.get("in_work", 0)
        checking = counts.get("wait_confirm", 0) + counts.get("in_review", 0)
        total_waiting = pending + in_work + checking

        lines.extend([
            f"⚙️ <b>КОНТУР ОЖИДАНИЯ ({total_waiting} шт):</b>",
            f" ┝ 📦 <b>СКЛАД:</b> <code>{pending}</code>",
            f" ┝ 📡 <b>РАБОТА:</b> <code>{in_work}</code>",
            f" ┕ ⏳ <b>ПРОВЕРКА:</b> <code>{checking}</code>",
            ""
        ])

        # 4. Лог последних изменений
        lines.append("📝 <b>ЛОГ ПОСЛЕДНИХ ИЗМЕНЕНИЙ:</b>")
        
        status_labels = {
            "accepted": "✅ ЗАЧЁТ ",
            "rejected": "⚠️ БРАК  ",
            "blocked": "💀 БЛОК  ",
            "not_a_scan": "🚫 НЕ СКАН",
            "pending": "📦 СКЛАД ",
            "in_work": "📡 РАБОТА",
            "wait_confirm": "⏳ ОТРАБ. ",
            "in_review": "🔍 ПРОВЕРКА"
        }

        if not submissions:
            lines.append(" <i>(нет активных записей в логе)</i>")
        else:
            from datetime import timezone, timedelta
            now_utc = datetime.now(timezone.utc)
            
            for s in submissions[:10]: 
                st_label = status_labels.get(s.status, s.status.upper()[:8])
                phone = s.phone_normalized or "N/A"
                # Формат: 7915***1234
                if len(phone) >= 11:
                    phone_display = f"{phone[:4]}***{phone[-4:]}"
                else:
                    phone_display = phone

                # Детализация
                detail = ""
                if s.status == "accepted":
                    detail = f"+{s.fixed_payout_rate} USDT"
                elif s.status in ("rejected", "blocked", "not_a_scan"):
                    detail = "ВОЗВРАТ"
                else:
                    updated_at = s.updated_at.replace(tzinfo=timezone.utc) if s.updated_at.tzinfo is None else s.updated_at
                    diff = now_utc - updated_at
                    if diff.total_seconds() < 60: detail = "только что"
                    elif diff.total_seconds() < 3600: detail = f"{int(diff.total_seconds()//60)} мин."
                    else: detail = "в процессе"

                lines.append(f" <code>{phone_display:13} │ {st_label} │ {detail}</code>")

        if len(submissions) > 10:
            lines.append(f" <i>* остальные записи доступны в Архиве (Личный профиль).</i>")

        # 5. Футер
        lines.extend([
            DIVIDER_LIGHT,
            f"🔄 Live Sync: <b>{now_time}</b> | <i>Авто-обновление 5с</i>"
        ])
        
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
        
        return "\n".join([
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
        ])

    def render_seller_settings(self, user: Any) -> str:
        """Отрисовка меню настроек."""
        alias = user.nickname or user.pseudonym or "не установлен"
        incognito = "ВКЛЮЧЕН 🎭" if user.is_incognito else "ВЫКЛЮЧЕН ▫️"
        silent = "ВЫКЛЮЧЕН 🔕" if user.is_silent_mode else "ВКЛЮЧЕН 🔔"

        return "\n".join([
            "⚙️ <b>GDPX // CONFIGURATION</b>",
            DIVIDER,
            f"👤 <b>ПСЕВДОНИМ:</b> <code>{escape(alias)}</code>",
            f"🎭 <b>РЕЖИМ INCOGNITO:</b> <code>{incognito}</code>",
            f"🔔 <b>ЗВУК УВЕДОМЛЕНИЙ:</b> <code>{silent}</code>",
            DIVIDER_LIGHT,
            "<b>ДОСТУПНЫЕ ОПЦИИ:</b>",
            " ├ Смена публичного имени",
            " ├ Шаблоны загрузки активов",
            " └ Экспорт данных в Excel",
            DIVIDER,
            "<i>Выберите категорию для изменения ↴</i>",
        ])

    def render_personal_data(self, user: Any, stats: Mapping[str, Any]) -> str:
        """Отрисовка экрана личных данных пользователя."""
        created_at = user.created_at.strftime("%d.%m.%Y")
        username = user.username or "не привязан"
        
        return "\n".join([
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
            f"💰 <b>К ВЫПЛАТЕ:</b> <code>{float(user.pending_balance or 0):.2f}</code> USDT",
            DIVIDER,
            "<i>Эти данные используются для внутренней идентификации.</i>"
        ])

    def render_dashboard(self, stats: Mapping[str, Any]) -> str:
        actor = str(stats.get("username") or "resident")
        greeting = get_time_greeting()
        return "\n".join([
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
            f" ├ ПРИНЯТО: <code>{int(stats.get('accepted') or stats.get('approved_count', 0))}</code>",
            f" ├ В ОБРАБОТКЕ: <code>{int(stats.get('pending') or stats.get('pending_count', 0))}</code>",
            f" └ ВЫПЛАЧЕНО: {format_currency(float(stats.get('balance') or stats.get('total_payout_amount', 0)))}",
            DIVIDER,
            "",
            self._get_agent_wisdom(),
            "",
            "<i>Выберите раздел системы:</i>",
        ])

    def render_queue_lobby(self, *, pending_count: int, in_work_count: int) -> str:
        return "\n".join([
            HEADER_QUEUE,
            DIVIDER,
            f"🔲 <b>PENDING (ОЧЕРЕДЬ):</b> <code>{int(pending_count)}</code>",
            f"📟 <b>SCANNING (НА СКАНЕ):</b> <code>{int(in_work_count)}</code>",
            DIVIDER,
            "<i>Модератор берет активы, которые УЖЕ выданы на скан.</i>"
        ])

    def render_owner_dashboard(self, stats: Mapping[str, Any]) -> str:
        actor = str(stats.get("username") or "Owner")
        greeting = get_time_greeting()
        total_debt = float(stats.get("total_debt", 0))
        paid_today = float(stats.get("paid_today", 0))
        active_mods = int(stats.get("active_mods", 0))
        warehouse = int(stats.get("warehouse", 0))
        volume_24h = float(stats.get("volume_24h", 0))
        top_op = str(stats.get("top_operator", "N/A"))

        return "\n".join([
            "🏯 <b>КОМАНДНЫЙ ЦЕНТР GDPX</b>",
            DIVIDER,
            f"👋 <b>{greeting}, {escape(actor)}</b>",
            "<i>Система управления активами активна.</i>",
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
            " ├ Статус: 🟢 <code>HEALTHY</code>",
            f" └ Пинг: <code>{random.randint(12, 28)}ms</code>",
            DIVIDER,
            "<i>Выберите приоритетное направление ↴</i>",
        ])

    def render_owner_finance(self, stats: Mapping[str, Any], pending_sellers: Sequence[Any]) -> str:
        lines = [
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
        return "\n".join([
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
        ])

    def render_moderation_audit(self, actions: list[dict], title: str = "АУДИТ ДЕЙСТВИЙ") -> str:
        lines = [
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
        return "\n".join([
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
        ])

    def render_cat_constructor_step(self, step: int, total_steps: int, title: str, description: str) -> str:
        return "\n".join([
            HEADER_CATCON,
            DIVIDER,
            f"🛠 <b>STAGE {step}/{total_steps} | {escape(title)}</b>",
            "",
            escape(description),
            DIVIDER_LIGHT,
        ])

    def render_category_manage(self, category: Any) -> str:
        priority = "🏮 PRIORITY" if getattr(category, "is_priority", False) else "▫️ STANDARD"
        status = "🟢 ACTIVE" if category.is_active else "🔴 DISABLED"
        return "\n".join([
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
        ])
