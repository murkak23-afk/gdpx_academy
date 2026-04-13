import asyncio
from src.database.session import SessionFactory
from src.domain.users.user_service import UserService

async def test():
    async with SessionFactory() as session:
        print("Creating UserService(session=session)")
        user_service = UserService(session=session)
        
        print("Calling user_service.get_by_telegram_id(123456)")
        user = await user_service.get_by_telegram_id(123456)
        print(f"Result: {user}")

if __name__ == "__main__":
    asyncio.run(test())
