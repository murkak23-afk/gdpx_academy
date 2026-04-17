import asyncio
import logging
from datetime import datetime, timezone
from aiogram import Bot
from sqlalchemy import select, and_
from src.database.session import SessionFactory
from src.database.uow import UnitOfWork
from src.domain.submission.submission_service import SubmissionService
from src.database.models.user import User
from src.database.models.web_control import SimbuyerPrice
from src.core.constants import DIVIDER

logger = logging.getLogger(__name__)

async def background_delivery_task(bot: Bot, category_id: int, buyer_id: int, chat_id: int, thread_id: int, count: int, ws_manager=None):
    """
    Фоновая задача выдачи eSIM. 
    Вынесена в отдельный сервис для предотвращения циклических импортов.
    """
    async with SessionFactory() as session:
        async with UnitOfWork(session=session) as uow:
            sub_svc = SubmissionService(uow)
            # Берем симки из очереди (метод уже переводит их в IN_WORK)
            items = await sub_svc.take_from_warehouse(category_id, count)

            if not items:
                logger.warning(f"⚠️ Склад пуст для категории {category_id}. Выдача в чат {chat_id} отменена.")
                return

            # Получаем персональную цену для этого покупателя
            price_stmt = select(SimbuyerPrice.price).where(
                and_(SimbuyerPrice.user_id == buyer_id, SimbuyerPrice.category_id == category_id)
            )
            price_val = (await session.execute(price_stmt)).scalar() or 0

            for item in items:
                # Фиксируем параметры выдачи
                item.buyer_id = buyer_id
                item.purchase_price = price_val
                item.delivered_to_chat = chat_id
                item.delivered_to_thread = thread_id
                item.assigned_at = datetime.now(timezone.utc)

                try:
                    # ТЗ 3: GDPX // Категория - заголовок, ниже ID, номер и время поступления
                    arrival_time = item.created_at.strftime('%d.%m.%Y %H:%M')
                    caption = (
                        f"<b>GDPX // {item.category.title}</b>\n"
                        f"━━━━━━━━━━━━━━━━━━\n\n"
                        f"🆔 <b>ID:</b> #{item.id}\n"
                        f"📱 <b>НОМЕР:</b> <code>{item.phone_normalized or 'N/A'}</code>\n"
                        f"🕒 <b>ПОСТУПИЛА:</b> {arrival_time}\n\n"
                        f"🍀 <i>Удачного скана и отработки материала!</i>"
                    )
                    
                    # Шлем в персональный чат/топик
                    await bot.send_photo(
                        chat_id=chat_id, 
                        photo=item.telegram_file_id, 
                        caption=caption, 
                        message_thread_id=thread_id if thread_id != 0 else None,
                        parse_mode="HTML"
                    )
                    await asyncio.sleep(0.3) # Анти-флуд
                except Exception as e:
                    logger.error(f"!!! SEND ERROR (Submission #{item.id}): {e}")
            
            await uow.commit()
            if ws_manager:
                await ws_manager.broadcast({
                    "type": "notification",
                    "message": f"🔥 НОВАЯ ВЫДАЧА: {len(items)} шт. {items[0].category.title if items else ""}",
                    "style": "success"
                })
            logger.info(f"✅ Успешно выдано {len(items)} шт. в чат {chat_id}")
