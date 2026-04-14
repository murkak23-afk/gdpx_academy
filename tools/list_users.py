import asyncio
from sqlalchemy import select
from src.database.models.user import User
from src.database.session import SessionFactory

async def list_users():
    async with SessionFactory() as session:
        stmt = select(User).order_by(User.id)
        res = await session.execute(stmt)
        users = res.scalars().all()
        
        print(f"{'ID':<5} | {'TG ID':<15} | {'Username':<20} | {'Role':<10} | {'Full Name'}")
        print("-" * 70)
        for user in users:
            print(f"{user.id:<5} | {user.telegram_id:<15} | {user.username or 'N/A':<20} | {user.role.value:<10} | {user.full_name}")

if __name__ == '__main__':
    asyncio.run(list_users())
