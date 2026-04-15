from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Update

from src.core.utils.message_manager import MessageManager
from src.core.ui import ui as ui_module   # ← переименовали
from src.core.logger import logger

class LoadingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        # 1. Инициализируем ui сразу, чтобы избежать NameError в блоке except
        ui: MessageManager | None = data.get("ui")
        callback: CallbackQuery | None = event.callback_query if isinstance(event, Update) else None

        if not callback:
            return await handler(event, data)

        if ui:
            # 1. Мгновенная реакция
            await ui.answer_loading(callback)
            
            # 2. Loading-состояние
            cd = callback.data or ""
            if not any(x in cd for x in ["incognito", "prefs", "lang_set", "toggle_", "sel_asset"]):
                await ui.show_loading(callback)

        try:
            return await handler(event, data)
        except Exception as e:
            # Безопасно проверяем наличие ui и callback перед использованием
            if ui and callback:
                try:
                    await ui.display(
                        event=callback, 
                        text="❌ <b>ОШИБКА ОБРАБОТКИ</b>\n\nПроизошла внутренняя ошибка при загрузке данных. Попробуйте позже или обратитесь в поддержку."
                    )
                except Exception as ui_e:
                    logger.error(f"Error displaying error message: {ui_e}")
            raise e