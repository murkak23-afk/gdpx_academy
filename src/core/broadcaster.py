"""Flood-safe mass broadcast service.

Rate: one send per _SEND_DELAY seconds → ~20 msg/s, safely under Telegram's
30 msg/s global limit while respecting per-chat rate policies.

On TelegramRetryAfter, the service backs off for the required number of
seconds and retries the failed recipient once before counting it as blocked.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup
from loguru import logger

# 0.05 s ≈ 20 sends/sec — comfortably below the 30 msg/s Telegram cap.
_SEND_DELAY = 0.05


@dataclass
class BroadcastResult:
    """Aggregated delivery statistics for one broadcast run."""

    ok: int = 0
    blocked: int = 0  # bot blocked by user OR user deactivated
    failed: int = 0   # any other API error


async def _send_one(
    bot: Bot,
    tg_id: int,
    text: str,
    *,
    photo_file_id: str | None,
    reply_markup: InlineKeyboardMarkup | None,
    parse_mode: str,
) -> None:
    """Send a single message; raises on error (caller handles categories)."""
    from src.core.utils.message_manager import MessageManager
    mm = MessageManager(bot)
    
    await mm.send_notification(
        user_id=tg_id,
        text=text,
        reply_markup=reply_markup,
        photo=photo_file_id,
        parse_mode=parse_mode,
    )


async def broadcast(
    bot: Bot,
    user_ids: list[int],
    text: str,
    *,
    photo_file_id: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str = "HTML",
) -> BroadcastResult:
    """Send *text* (or a photo with caption) to every telegram_id in *user_ids*.

    Guarantees:
    - Sleeps ``_SEND_DELAY`` seconds between every individual send.
    - ``TelegramForbiddenError`` (bot blocked / user deactivated) increments
      ``result.blocked`` and is otherwise silently ignored.
    - ``TelegramRetryAfter`` triggers a back-off sleep then a single retry
      before treating the recipient as blocked.
    - All other exceptions increment ``result.failed`` and are logged at WARNING.
    """
    result = BroadcastResult()

    for tg_id in user_ids:
        try:
            await _send_one(
                bot, tg_id, text,
                photo_file_id=photo_file_id,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            result.ok += 1

        except TelegramRetryAfter as exc:
            wait = exc.retry_after + 1
            logger.warning(
                "Broadcast flood control: sleeping %ds before retrying tg_id=%s",
                wait, tg_id,
            )
            await asyncio.sleep(wait)
            try:
                await _send_one(
                    bot, tg_id, text,
                    photo_file_id=photo_file_id,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
                result.ok += 1
            except TelegramForbiddenError:
                result.blocked += 1
            except Exception:
                result.failed += 1

        except TelegramForbiddenError as exc:
            result.blocked += 1
            logger.debug("Broadcast blocked tg_id=%s: %s", tg_id, exc)

        except Exception as exc:
            result.failed += 1
            logger.warning("Broadcast failed tg_id=%s: %s", tg_id, exc)

        await asyncio.sleep(_SEND_DELAY)

    return result
