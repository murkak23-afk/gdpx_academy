from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.fsm.context import FSMContext

class ForceClearFSMOnStartOrCancel(BaseMiddleware):
    async def __call__(self, handler, event, data):
        message = data.get("event_message")
        state: FSMContext = data.get("state")
        if message and state:
            if message.text in ("/start", "/cancel"):
                await state.clear()
        return await handler(event, data)
