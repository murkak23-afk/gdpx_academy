import asyncio
from aiogram import Bot, Dispatcher, types

# ВСТАВЬ СВОЙ ТОКЕН СЮДА
TOKEN = "YOUR_BOT_TOKEN_HERE"

async def get_file_id(message: types.Message):
    if message.photo:
        file_id = message.photo[-1].file_id
        print(f"\n[SUCCESS] Твой File ID:")
        print(f"BANNER_MAIN = '{file_id}'\n")
        await message.answer(f"ID сохранен: <code>{file_id}</code>", parse_mode="HTML")

async def main():
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.message.register(get_file_id)
    print("Бот запущен. Скинь картинку в телегу...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())