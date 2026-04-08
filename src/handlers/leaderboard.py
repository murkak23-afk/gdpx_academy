from __future__ import annotations

from decimal import Decimal

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.user import User
from src.keyboards.callbacks import (
    CB_LEADERBOARD_OPEN,
    CB_LEADERBOARD_REFRESH,
    CB_SELLER_MENU_HOME,
)
from src.services.leaderboard_service import (
    LeaderboardService,
    LeaderboardSettingsService,
    week_number,
)
from src.utils.formatters import get_rank_info
from src.utils.media_screen import BANNER_LEADERBOARD, media_transition
from src.utils.text_format import edit_message_text_or_caption_safe as edit_message_text_safe

router = Router(name="leaderboard-router")

_MEDALS = ["🥇", "🥈", "🥉", "▪️", "▪️"]
_DIVIDER = "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰"


# ── Text / keyboard builders ───────────────────────────────────────────────


def _leaderboard_text(
    top5: list[dict],
    *,
    prize_enabled: bool,
    prize_text: str | None,
    user_rank: int,
    user_score: int,
    user_turnover: Decimal,
) -> str:
    week = week_number()
    lines = [f"❖ <b>GDPX // LEADERBOARD #{week}</b>"]

    if prize_enabled and prize_text:
        lines += [
            "",
            "⚠️ <b>ВОЗНАГРАЖДЕНИЕ[БОНУС]:</b>",
            f"<i>{prize_text}</i>",
            _DIVIDER,
        ]
    else:
        lines += ["", "<code>[ТОП-5 СЕЛЛЕРОВ]</code>", ""]

    if not top5:
        lines.append("🌑 <b>ЛОГОВ НЕТ</b>")
        lines.append(" └<i>Трафик за текущий цикл не зафиксирован.</i>")
    else:
        for i, row in enumerate(top5):
            medal = _MEDALS[i]
            name = row["pseudonym"] or "INCOGNITO"
            score = row["score"]
            rank_label, _ = get_rank_info(row.get("turnover", Decimal("0")))
            lines.append(f"{medal} <b>{name}</b> <code>{rank_label}</code> → <code>{score}</code> шт.")

    lines += ["", _DIVIDER]

    # ── Твоя позиция ──────────────────────────────────────────────────────
    user_rank_label, user_next_threshold = get_rank_info(user_turnover)

    if user_rank > 0:
        # Индикатор текущего ранга и его статус
        lines.append(f"► <b>[ТВОЙ РАНГ] // РАНГ: #{user_rank}</b>  <code>{user_rank_label}</code>")
        lines.append(f"  ├ ОБОРОТ:  <code>{float(user_turnover):.2f} USDT</code>")
        lines.append(f"  ├ АКТИВОВ: <code>{user_score} шт.</code>")
    else:
        lines.append(f"► <b>[ТВОЙ РАНГ]:</b> <code>{user_rank_label}</code>")
        lines.append("   ├ <i>Мы ждём твой материал!</i>")

    # Вывод прогресса до следующего уровня допуска
    if user_next_threshold is not None:
        remaining = max(float(user_next_threshold) - float(user_turnover), 0.0)
        lines.append(f"  └ <i>До апгрейда: <code>{remaining:.2f} USDT</code></i>")
    else:
        lines.append("  └ <code>[ MAX TIER // МАКСИМАЛЬНЫЙ РАНГ ПОЛУЧЕН ]</code>")

    return "\n".join(lines)


def _leaderboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="↻ ОБНОВИТЬ", callback_data=CB_LEADERBOARD_REFRESH)],
            [InlineKeyboardButton(text="◂ В МЕНЮ", callback_data=CB_SELLER_MENU_HOME)],
        ]
    )


# ── Helpers ────────────────────────────────────────────────────────────────


async def _resolve_internal_user_id(session: AsyncSession, telegram_id: int) -> int:
    row = (await session.execute(select(User.id).where(User.telegram_id == telegram_id))).scalar_one_or_none()
    return row or 0


# ── Seller: open / refresh leaderboard ────────────────────────────────────


@router.callback_query(F.data == CB_LEADERBOARD_OPEN)
@router.callback_query(F.data == CB_LEADERBOARD_REFRESH)
async def on_leaderboard_open(callback: CallbackQuery, session: AsyncSession) -> None:
    if callback.from_user is None or callback.message is None:
        return

    is_refresh = callback.data == CB_LEADERBOARD_REFRESH

    if is_refresh:
        await callback.answer("✅ Данные обновлены")
    else:
        await callback.answer("⏳ Синхронизация данных...")

    lead_svc = LeaderboardService(session=session)
    settings_svc = LeaderboardSettingsService(session=session)

    top5 = await lead_svc.get_top5()
    settings = await settings_svc.get()
    internal_id = await _resolve_internal_user_id(session, callback.from_user.id)
    user_rank, user_score = await lead_svc.get_user_rank(internal_id)
    user_turnover = await lead_svc.get_user_turnover(internal_id)

    text = _leaderboard_text(
        top5,
        prize_enabled=settings.prize_enabled,
        prize_text=settings.prize_text,
        user_rank=user_rank,
        user_score=user_score,
        user_turnover=user_turnover,
    )

    await media_transition(
        callback,
        banner_file_id=BANNER_LEADERBOARD,
        caption=text,
        reply_markup=_leaderboard_keyboard(),
        answered=True,
    )


# Admin /alead handlers → src/handlers/admin/leaderboard_admin.py
