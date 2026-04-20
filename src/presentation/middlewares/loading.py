from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Update

from src.core.utils.message_manager import MessageManager


class LoadingMiddleware(BaseMiddleware):
    """
    Middleware для мгновенных реакций и loading-состояний.
    Реализует Шаг 7 оптимизации UX.
    """

    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        if not isinstance(event, Update) or not event.callback_query:
            return await handler(event, data)

        callback: CallbackQuery = event.callback_query
        ui: MessageManager = data.get("ui")

        if ui:
            # 1. Мгновенная реакция (callback.answer)
            # Это убирает "часики" у кнопки
            await ui.answer_loading(callback)
            
            # 2. Loading-состояние (опционально)
            # Мы его убираем из middleware, так как оно часто конфликтует 
            # с быстрыми ответами хендлеров.

        try:
            return await handler(event, data)
        except Exception as e:
            # Если произошла ошибка в хендлере после показа Loading, 
            # возвращаем человекочитаемую ошибку вместо бесконечного спиннера.
            if ui:
                await ui.display(
                    event=callback, 
                    text="❌ <b>ОШИБКА ОБРАБОТКИ</b>\n\nПроизошла внутренняя ошибка при загрузке данных. Попробуйте позже или обратитесь в поддержку."
                )
            raise e
