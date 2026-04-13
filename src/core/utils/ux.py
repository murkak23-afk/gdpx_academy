from aiogram.types import Message


async def send_typing_action(message: Message):
    await message.chat.do("typing")
