import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import TelegramObject, Message, CallbackQuery
from loguru import logger

class FSMTimeoutMiddleware(BaseMiddleware):
    """
    Middleware для сброса стейта пользователя, если он не проявлял 
    активности более заданного времени (например, 24 часа).
    Предотвращает зависание пользователей в тупиковых ветках.
    """
    
    def __init__(self, timeout_seconds: int = 86400):
        self.timeout_seconds = timeout_seconds
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        state: FSMContext = data.get("state")
        if not state:
            return await handler(event, data)

        current_state = await state.get_state()
        if current_state:
            state_data = await state.get_data()
            last_activity = state_data.get("_last_activity", 0)
            now = time.time()

            if last_activity and (now - last_activity > self.timeout_seconds):
                logger.info(f"FSM Timeout triggered. Resetting state '{current_state}' for user.")
                
                user_id = data.get("event_from_user").id if data.get("event_from_user") else None
                if user_id:
                    # Принудительная очистка локальных буферов
                    from src.presentation.seller_portal.seller.submission import _media_buffer, _debounce_tasks
                    _media_buffer.pop(user_id, None)
                    task = _debounce_tasks.pop(user_id, None)
                    if task:
                        task.cancel()

                await state.clear()
                
                # Уведомляем пользователя, если это возможно
                bot = data.get("bot")
                
                if user_id and bot:
                    try:
                        await bot.send_message(
                            user_id, 
                            "🕒 <b>Таймаут сессии</b>\nВаш предыдущий процесс был отменен из-за неактивности (>24ч).\nПожалуйста, начните заново.",
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.debug(f"Failed to send FSM timeout notification: {e}")
            else:
                # Обновляем метку времени активности
                await state.update_data(_last_activity=now)

        return await handler(event, data)
