import asyncio

from aiogram import Bot

from src.core.config import Settings


async def main():
    settings = Settings()
    token = settings.bot_token
    bot = Bot(token=token)
    
    print("Enabling bot by deleting webhook...")
    try:
        # This will resume long polling
        await bot.delete_webhook(drop_pending_updates=True)
        print("✅ Webhook deleted and updates dropped. System ready.")
    except Exception as e:
        print(f"❌ Error deleting webhook: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
