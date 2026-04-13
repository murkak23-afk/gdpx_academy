"""Фоновая проверка заявок IN_REVIEW без движения дольше порога."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.config import get_settings
from src.domain.submission.submission_service import SubmissionService

logger = logging.getLogger(__name__)

_stuck_alerted_once: set[int] = set()


async def run_in_review_stuck_monitor(bot: Bot, session_factory: async_sessionmaker) -> None:
    """Раз в 10 минут: 
    1. IN_WORK (> 1 часа) → WAIT_CONFIRM (в раздел ПРОВЕРКА).
    2. IN_REVIEW (> 40 мин) → Алерт в админ-чат.
    """

    while True:
        try:
            await asyncio.sleep(600)
            settings = get_settings()
            now = datetime.now(timezone.utc)

            async with session_factory() as session:
                sub_svc = SubmissionService(session=session)
                
                # 1. Авто-перевод из Выданных в Проверку
                threshold_issued = now - timedelta(hours=1)
                moved_count = await sub_svc.auto_transition_issued_to_verification(threshold_issued)
                if moved_count > 0:
                    logger.info(f"Monitor: {moved_count} items moved to WAIT_CONFIRM (auto-verification)")

                # 2. Алерты по зависшим IN_REVIEW
                if settings.moderation_chat_id != 0:
                    threshold_review = now - timedelta(minutes=40)
                    stuck = await sub_svc.list_in_review_stale(threshold_review)

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
                
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ошибка тика мониторинга IN_REVIEW")
