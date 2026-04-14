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

async def background_delivery_task(bot: Bot, category_id: int, chat_id: int, thread_id: int, count: int):
    """
    Фоновая задача выдачи eSIM. 
    Вынесена в отдельный сервис для предотвращения циклических импортов.
    """
    async with SessionFactory() as session:
        async with UnitOfWork(session=session) as uow:
            sub_svc = SubmissionService(uow)
            # Берем симки из очереди (метод уже переводит их в IN_WORK)
            items = await sub_svc.get_material_from_warehouse_batch(category_id, count)

            if not items:
                logger.warning(f"⚠️ Склад пуст для категории {category_id}. Выдача в чат {chat_id} отменена.")
                return

            # Получаем персональную цену для этого чата (покупателя)
            buyer_stmt = select(User).where(User.telegram_id == chat_id)
            buyer = (await session.execute(buyer_stmt)).scalar_one_or_none()

            price_val = 0
            if buyer:
                price_stmt = select(SimbuyerPrice.price).where(
                    and_(SimbuyerPrice.user_id == buyer.id, SimbuyerPrice.category_id == category_id)
                )
                price_val = (await session.execute(price_stmt)).scalar() or 0

            for item in items:
                # Фиксируем параметры выдачи
                item.purchase_price = price_val
                item.delivered_to_chat = chat_id
                item.delivered_to_thread = thread_id
                item.assigned_at = datetime.now(timezone.utc)

                try:
                    caption = (
                        f"📟 <b>eSIM #{item.id}</b>\n"
                        f"📶 <b>ОПЕРАТОР:</b> {item.category.title}\n"
                        f"📞 <b>НОМЕР:</b> <code>{item.phone_normalized or 'N/A'}</code>\n"
                        f"{DIVIDER}\n"
                        f"👤 <b>АГЕНТ:</b> @{item.seller.username or 'id' + str(item.seller.telegram_id)}"
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
            logger.info(f"✅ Успешно выдано {len(items)} шт. в чат {chat_id}")
