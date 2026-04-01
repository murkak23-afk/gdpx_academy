"""Фоновая проверка заявок IN_REVIEW без движения дольше порога."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.config import get_settings
from src.services.submission_service import SubmissionService

logger = logging.getLogger(__name__)

_stuck_alerted_once: set[int] = set()


async def run_in_review_stuck_monitor(bot: Bot, session_factory: async_sessionmaker) -> None:
    """Раз в 10 минут: IN_REVIEW старше 40 минут → одно уведомление в админ-чат на заявку (пока висит)."""

    while True:
        try:
            await asyncio.sleep(600)
            settings = get_settings()
            if settings.moderation_chat_id == 0:
                continue

            threshold = datetime.now(timezone.utc) - timedelta(minutes=40)
            async with session_factory() as session:
                stuck = await SubmissionService(session=session).list_in_review_stale(threshold)

            current = {s.id for s in stuck}
            _stuck_alerted_once.intersection_update(current)

            for s in stuck:
                if s.id in _stuck_alerted_once:
                    continue
                admin = s.admin
                uname = (admin.username if admin is not None else None) or "unknown"
                text = f"⚠️ Внимание! Заявка #{s.id} зависла у админа @{uname}!"
                try:
                    await bot.send_message(chat_id=settings.moderation_chat_id, text=text)
                    _stuck_alerted_once.add(s.id)
                except TelegramAPIError as exc:
                    logger.warning("Не удалось отправить алерт по заявке %s: %s", s.id, exc)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ошибка тика мониторинга IN_REVIEW")
