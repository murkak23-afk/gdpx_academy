from __future__ import annotations
import asyncio
import logging
import re
import json
import unicodedata
from aiogram import Router, F, Bot
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.config import get_settings
from src.database.models.enums import SubmissionStatus
from src.domain.moderation.moderation_service import ModerationService
from src.core.cache import get_redis
from src.core.constants import DIVIDER

router = Router(name="auto-fix-router")
logger = logging.getLogger(__name__)

# Хранилище активных задач для буферизации {chat_id:thread_id:status: task}
_active_tasks: dict[str, asyncio.Task] = {}

def normalize_digits(text: str) -> str:
    """Преобразует любые Unicode-цифры в стандартные 0-9."""
    return "".join(c if not c.isdigit() else str(unicodedata.decimal(c, c)) for c in text)

async def send_buffered_report(chat_id: int, thread_id: int, status_key: str, last_message: Message, bot: Bot):
    """Ожидает 5 секунд, собирает данные из Redis и отправляет отчет."""
    await asyncio.sleep(5)
    
    redis = await get_redis()
    if not redis: return

    cache_key = f"af_buf:{chat_id}:{thread_id}:{status_key}"
    
    # Извлекаем все накопленные результаты
    raw_data = await redis.get(cache_key)
    if not raw_data:
        _active_tasks.pop(f"{chat_id}:{thread_id}:{status_key}", None)
        return

    results = json.loads(raw_data)
    # Очищаем буфер сразу после извлечения
    await redis.delete(cache_key)
    _active_tasks.pop(f"{chat_id}:{thread_id}:{status_key}", None)

    if not results: return

    # Формируем заголовок
    headers = {
        "blocked": "🚫 <b>ФИКСИРУЮ БЛОКИ:</b>",
        "not_a_scan": "🗑 <b>ФИКСИРУЮ НЕ СКАНЫ:</b>",
        "accepted": "✅ <b>ФИКСИРУЮ ЗАЧЕТЫ:</b>",
        "rejected": "❌ <b>ОТКЛОНЯЮ ЗАЯВКИ:</b>"
    }
    header = headers.get(status_key, "⚙️ <b>ОБРАБОТКА ЗАВЕРШЕНА:</b>")
    lines = [header]

    if len(results) == 1:
        phone, sub_id = results[0]
        lines.append(f"      └ <code>{phone}</code> [ID: {sub_id}]")
    else:
        for i, (phone, sub_id) in enumerate(results):
            prefix = "  ┝ " if i < len(results) - 1 else "  ╰ "
            lines.append(f"{prefix}<code>{phone}</code> [ID: {sub_id}]")

    try:
        # Отвечаем на последнее сообщение в цепочке
        await last_message.reply("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Failed to send buffered report: {e}")

@router.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_auto_fix(message: Message, session: AsyncSession, bot: Bot):
    """
    Массовая авто-фиксация статусов с буферизацией в 5 секунд.
    """
    settings = get_settings()
    if not settings.auto_fix_enabled: return

    raw_text = message.text or message.caption or ""
    if not raw_text or raw_text.startswith("/"): return

    chat_id = message.chat.id
    thread_id = message.message_thread_id or 0
    
    chat_cfg = settings.auto_fix_chats.get(chat_id) or settings.auto_fix_chats.get(str(chat_id))
    if not chat_cfg: return

    forced_status_key = chat_cfg.get(thread_id) or chat_cfg.get(str(thread_id))
    if not forced_status_key: return 

    status_map = {
        "blocked": SubmissionStatus.BLOCKED,
        "not_a_scan": SubmissionStatus.NOT_A_SCAN,
        "accepted": SubmissionStatus.ACCEPTED,
        "rejected": SubmissionStatus.REJECTED
    }
    target_status = status_map.get(forced_status_key)
    if not target_status: return

    # 1. Парсинг номеров
    normalized_text = normalize_digits(raw_text)
    found_sequences = re.findall(r'\d{4,11}', normalized_text)
    if not found_sequences: return

    mod_svc = ModerationService(session=session)
    redis = await get_redis()
    new_results = []
    
    # 2. Обработка номеров
    for raw_digits in found_sequences:
        search_term = raw_digits
        if len(raw_digits) == 10 and raw_digits.startswith("9"):
            search_term = "7" + raw_digits
        elif len(raw_digits) == 11 and raw_digits.startswith("8"):
            search_term = "7" + raw_digits[1:]

        item = None
        for search_status in [SubmissionStatus.IN_WORK, SubmissionStatus.WAIT_CONFIRM, SubmissionStatus.IN_REVIEW]:
            item, match_len = await mod_svc.smart_find_by_phone_suffix(search_term, search_status=search_status)
            if item and match_len >= 4: break
            else: item = None

        if not item: continue

        success = await mod_svc.finalize_submission(
            submission_id=item.id,
            status=target_status,
            admin_id=1,
            bot=bot,
            comment=f"Auto-fix buffer ({match_len} digits): {raw_digits}"
        )
        
        if success:
            new_results.append((item.phone_normalized, item.id))

    if not new_results: return

    # 3. Сохранение в буфер (Redis)
    cache_key = f"af_buf:{chat_id}:{thread_id}:{forced_status_key}"
    existing_raw = await redis.get(cache_key)
    existing_data = json.loads(existing_raw) if existing_raw else []
    
    # Добавляем только те, которых еще нет в буфере (защита от дублей)
    seen_ids = {r[1] for r in existing_data}
    for res in new_results:
        if res[1] not in seen_ids:
            existing_data.append(res)
    
    await redis.set(cache_key, json.dumps(existing_data), ex=60)

    # 4. Запуск или обновление задачи отчета
    task_id = f"{chat_id}:{thread_id}:{forced_status_key}"
    if task_id not in _active_tasks or _active_tasks[task_id].done():
        _active_tasks[task_id] = asyncio.create_task(
            send_buffered_report(chat_id, thread_id, forced_status_key, message, bot)
        )
