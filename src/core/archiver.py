"""Фоновая задача архивации симок (ежедневно в 23:30 МСК)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker
from src.services.submission_service import SubmissionService

logger = logging.getLogger(__name__)

async def run_archiver(session_factory: async_sessionmaker) -> None:
    """Проверяет время каждую минуту. Если 23:30 МСК — запускает архивацию."""
    
    # МСК = UTC + 3
    MSK_OFFSET = timedelta(hours=3)
    
    last_archived_date = None
    
    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            now_msk = now_utc + MSK_OFFSET
            
            # Проверяем, наступило ли время 23:30
            if now_msk.hour == 23 and now_msk.minute == 30:
                current_date = now_msk.date()
                
                # Чтобы не архивировать несколько раз в течение одной минуты 23:30
                if last_archived_date != current_date:
                    logger.info("Начало ежедневной автоматической архивации (23:30 МСК)...")
                    
                    async with session_factory() as session:
                        service = SubmissionService(session=session)
                        count = await service.archive_daily_submissions()
                        await session.commit()
                        
                    logger.info(f"Архивация завершена. Заархивировано записей: {count}")
                    last_archived_date = current_date
            
            # Спим 30 секунд, чтобы не пропустить минуту
            await asyncio.sleep(30)
            
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Ошибка в цикле архиватора")
            await asyncio.sleep(60)
