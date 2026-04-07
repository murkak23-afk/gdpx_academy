import asyncio
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

class AntiFloodMiddleware(BaseMiddleware):
    def __init__(self, rate_limit=1.0):
        self.rate_limit = rate_limit
        self._user_timestamps = {}

    async def __call__(self, handler, event, data):
        message: Message = data.get("event_message")
        if not message or not message.from_user:
            return await handler(event, data)
        user_id = message.from_user.id
        now = asyncio.get_event_loop().time()
        last = self._user_timestamps.get(user_id, 0)
        if now - last < self.rate_limit:
            await message.answer("⏳ Пожалуйста, не флудите. Подождите пару секунд.")
            return
        self._user_timestamps[user_id] = now
        return await handler(event, data)
