"""Admin System Integrity Monitor — Stage 10.

Handlers
────────
CB_ADMIN_SYSTEM_STATUS    → on_admin_system_status
    Runs three async probes concurrently:
      1. PostgreSQL: executes SELECT 1 via the request-scoped session.
      2. Redis: sends PING via a short-lived aioredis client.
      3. Active nodes in last 24 h: COUNT users with updated_at >= now-24h.
    Renders the integrity report and offers [ 🧹 CLEAR EXPIRED FSM ] button.

CB_ADMIN_SYSTEM_CLEAR_FSM → on_admin_system_clear_fsm
    Scans all FSM keys via SCAN and deletes those whose TTL has expired
    (i.e. no TTL set AND the key is orphaned because the user has no current
    state data that matches a known aiogram key pattern).
    In practice: deletes all aiogram FSM keys that carry no "state" field —
    these are ghost keys left by crashed sessions.
"""

from __future__ import annotations

import asyncio
from loguru import logger
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.uptime import get_uptime_str
from src.database.models.user import User
from src.keyboards import REPLY_BTN_BACK
from src.keyboards.callbacks import (
    CB_ADMIN_SYSTEM_CLEAR_FSM,
    CB_ADMIN_SYSTEM_STATUS,
)
from src.keyboards.constants import CALLBACK_INLINE_BACK
from src.services import AdminService
from src.utils.text_format import edit_message_text_safe

router = Router(name="admin-system-router")

DIVIDER = "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰"

# ── Keyboards ─────────────────────────────────────────────────────────────


def _status_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="↻ ОБНОВИТЬ", callback_data=CB_ADMIN_SYSTEM_STATUS)],
            [InlineKeyboardButton(text="🧹 CLEAR EXPIRED FSM", callback_data=CB_ADMIN_SYSTEM_CLEAR_FSM)],
            [InlineKeyboardButton(text=REPLY_BTN_BACK, callback_data=CALLBACK_INLINE_BACK)],
        ]
    )


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀ К СТАТУСУ", callback_data=CB_ADMIN_SYSTEM_STATUS)],
        ]
    )


# ── Probes ─────────────────────────────────────────────────────────────────


async def _probe_db(session: AsyncSession) -> bool:
    """Ping PostgreSQL via the current request session."""
    try:
        await session.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("System probe DB failed: %s", exc)
        return False


async def _probe_redis() -> bool:
    """Open a throw-away Redis connection and send PING."""
    settings = get_settings()
    _DEFAULT = "redis://localhost:6379/0"
    url = settings.redis_url or _DEFAULT
    client = Redis.from_url(url, socket_connect_timeout=2)
    try:
        await client.ping()
        return True
    except (RedisConnectionError, OSError, Exception) as exc:
        logger.warning("System probe Redis failed: %s", exc)
        return False
    finally:
        await client.aclose()


async def _count_active_nodes(session: AsyncSession) -> int:
    """Count users who had any DB activity in the last 24 hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    stmt = select(func.count(User.id)).where(User.updated_at >= cutoff)
    result = await session.execute(stmt)
    return int(result.scalar_one())


# ── Report renderer ────────────────────────────────────────────────────────


def _render_report(db_ok: bool, redis_ok: bool, nodes: int) -> str:
    db_line = "ONLINE [OK]" if db_ok else "⚠️ OFFLINE"
    redis_line = "ONLINE [OK]" if redis_ok else "⚠️ OFFLINE"
    uptime = get_uptime_str()
    return (
        f"❖ <b>SYSTEM INTEGRITY // REPORT</b>\n"
        f"{DIVIDER}\n"
        f"┕ DATABASE: <code>{db_line}</code>\n"
        f"┕ CACHE/FSM: <code>{redis_line}</code>\n"
        f"┕ ACTIVE NODES: <code>{nodes}</code>\n"
        f"┕ UPTIME: <code>{uptime}</code>"
    )


# ── Handlers ──────────────────────────────────────────────────────────────


@router.callback_query(F.data == CB_ADMIN_SYSTEM_STATUS)
async def on_admin_system_status(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    if callback.from_user is None or callback.message is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("НЕДОСТАТОЧНО ПРАВ", show_alert=True)
        return

    await callback.answer()

    # Show spinner immediately, then replace with real data
    await edit_message_text_safe(
        callback.message,
        "🛡 <b>SYSTEM INTEGRITY</b>\n\n⏳ Диагностика…",
        parse_mode="HTML",
    )

    db_ok, redis_ok, nodes = await asyncio.gather(
        _probe_db(session),
        _probe_redis(),
        _count_active_nodes(session),
    )

    await edit_message_text_safe(
        callback.message,
        _render_report(db_ok, redis_ok, nodes),
        reply_markup=_status_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == CB_ADMIN_SYSTEM_CLEAR_FSM)
async def on_admin_system_clear_fsm(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """Delete orphaned aiogram FSM keys from Redis.

    Strategy: scan for all keys matching aiogram's namespace pattern
    ``fsm:*``. For each key that is a Hash and contains NO ``state`` field
    (ghost entry), delete it.  This is safe because a live FSM entry always
    has at least a ``state`` or ``data`` field written by aiogram.
    """
    if callback.from_user is None or callback.message is None:
        return
    if not await AdminService(session=session).is_admin(callback.from_user.id):
        await callback.answer("НЕДОСТАТОЧНО ПРАВ", show_alert=True)
        return

    await callback.answer()
    await edit_message_text_safe(
        callback.message,
        "🧹 <b>CLEAR EXPIRED FSM</b>\n\n⏳ Сканирую Redis…",
        parse_mode="HTML",
    )

    settings = get_settings()
    _DEFAULT = "redis://localhost:6379/0"
    url = settings.redis_url or _DEFAULT

    deleted = 0
    scanned = 0
    error_msg: str | None = None

    client = Redis.from_url(url, socket_connect_timeout=3)
    try:
        # aiogram RedisStorage uses key pattern: fsm:{bot_id}:{chat_id}:{user_id}:*
        # We scan broadly and inspect each hash.
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor=cursor, match="fsm:*", count=200)
            for key in keys:
                scanned += 1
                key_type = await client.type(key)
                if key_type != b"hash":
                    continue
                has_state = await client.hexists(key, "state")
                has_data = await client.hexists(key, "data")
                if not has_state and not has_data:
                    await client.delete(key)
                    deleted += 1
            if cursor == 0:
                break
    except Exception as exc:
        logger.warning("FSM clear failed: %s", exc)
        error_msg = str(exc)
    finally:
        await client.aclose()

    if error_msg:
        result_text = (
            f"🧹 <b>CLEAR EXPIRED FSM</b>\n\n"
            f"⚠️ ОШИБКА ПРИ ОЧИСТКЕ:\n<code>{error_msg}</code>"
        )
    else:
        result_text = (
            f"🧹 <b>CLEAR EXPIRED FSM</b>\n\n"
            f"┕ ПРОВЕРЕНО КЛЮЧЕЙ: <code>{scanned}</code>\n"
            f"┕ УДАЛЕНО УСТАРЕВШИХ: <code>{deleted}</code>"
        )

    await edit_message_text_safe(
        callback.message,
        result_text,
        reply_markup=_back_keyboard(),
        parse_mode="HTML",
    )
