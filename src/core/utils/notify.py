"""Shared bulk-notification helper.

Extracted from ``src.presentation.admin_panel.admin_menu`` so that any module that needs
to fire-and-forget a large batch of Telegram messages can import this
without pulling in the whole admin-menu handler tree.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup


async def notify_bulk_with_progress(
    bot: Bot,
    notifications: list[tuple[int, str] | tuple[int, str, InlineKeyboardMarkup | None]],
    *,
    concurrency: int = 20,
    progress_step: int = 10,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> tuple[int, int]:
    """Параллельно отправляет уведомления с ограничением и прогрессом.

    Args:
        bot: Bot instance.
        notifications: Список кортежей (chat_id, text) или (chat_id, text, reply_markup).
        concurrency: Максимальное кол-во одновременных запросов.
        progress_step: Через сколько отправленных вызывать on_progress.
        on_progress: Async-callback(done, total) для отображения прогресса.

    Returns:
        (ok_count, fail_count)
    """
    total = len(notifications)
    if total == 0:
        return 0, 0

    sem = asyncio.Semaphore(max(concurrency, 1))
    lock = asyncio.Lock()
    ok_count = 0
    fail_count = 0
    processed = 0

    async def _send_one(
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        nonlocal ok_count, fail_count, processed
        try:
            async with sem:
                from src.core.utils.message_manager import MessageManager
                mm = MessageManager(bot)
                await mm.send_notification(user_id=chat_id, text=text, reply_markup=reply_markup)
            ok = True
        except TelegramAPIError:
            ok = False

        should_report = False
        processed_now = 0
        async with lock:
            processed += 1
            if ok:
                ok_count += 1
            else:
                fail_count += 1
            processed_now = processed
            should_report = (
                processed_now % max(progress_step, 1) == 0
                or processed_now == total
            )

        if should_report and on_progress is not None:
            await on_progress(processed_now, total)

    await asyncio.gather(
        *(
            _send_one(item[0], item[1], item[2] if len(item) > 2 else None)  # type: ignore[arg-type]
            for item in notifications
        )
    )
    return ok_count, fail_count
