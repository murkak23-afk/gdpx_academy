import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from src.domain.users.user_service import UserService
from src.database.models.base import Base

async def test():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    
    async with async_session() as session:
        print("Creating UserService(session=session)")
        user_service = UserService(session=session)
        
        print("Calling user_service.get_by_telegram_id(123456)")
        user = await user_service.get_by_telegram_id(123456)
        print(f"Result: {user}")

if __name__ == "__main__":
    asyncio.run(test())
