import asyncio
import argparse
from src.database.session import SessionFactory
from src.database.models.user import User
from src.database.models.web_control import WebAccount
from src.services.auth_service import AuthService
from src.database.models.enums import UserRole
from sqlalchemy import select

async def create_web_account(telegram_id: int, login: str, password: str, role: str):
    async with SessionFactory() as session:
        # 1. Проверяем или создаем пользователя в основной таблице
        stmt = select(User).where(User.telegram_id == telegram_id)
        user = (await session.execute(stmt)).scalar_one_or_none()
        
        if not user:
            print(f"User with ID {telegram_id} not found in 'users' table. Creating...")
            user = User(
                telegram_id=telegram_id,
                username=login,
                full_name=login,
                role=UserRole(role.lower())
            )
            session.add(user)
            await session.flush()
        else:
            user.role = UserRole(role.lower())
            print(f"User found. Updating role to {role}...")

        # 2. Создаем или обновляем веб-аккаунт
        stmt_web = select(WebAccount).where(WebAccount.user_id == user.id)
        web_acc = (await session.execute(stmt_web)).scalar_one_or_none()
        
        hashed_pw = AuthService.hash_password(password)
        
        if web_acc:
            web_acc.login = login
            web_acc.password_hash = hashed_pw
            print(f"Web account for {login} updated.")
        else:
            web_acc = WebAccount(
                user_id=user.id,
                login=login,
                password_hash=hashed_pw
            )
            session.add(web_acc)
            print(f"Web account for {login} created.")
            
        await session.commit()
        print("Success! You can now login to Nexus.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=int, required=True)
    parser.add_argument("--login", type=str, required=True)
    parser.add_argument("--password", type=str, required=True)
    parser.add_argument("--role", type=str, default="owner")
    args = parser.parse_args()
    
    asyncio.run(create_web_account(args.id, args.login, args.password, args.role))
