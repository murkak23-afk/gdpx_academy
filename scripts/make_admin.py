
import asyncio
import sys
from sqlalchemy import select
from src.database.session import SessionFactory
from src.database.models.user import User
from src.database.models.enums import UserRole

async def set_user_role(tg_id: int, role_name: str):
    async with SessionFactory() as session:
        # Ищем пользователя
        stmt = select(User).where(User.telegram_id == tg_id)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()
        
        if not user:
            print(f"❌ Пользователь с TG ID {tg_id} не найден в базе!")
            return

        try:
            new_role = UserRole(role_name.lower())
            user.role = new_role
            await session.commit()
            print(f"✅ Роль пользователя @{user.username or user.telegram_id} изменена на: {new_role.value}")
        except ValueError:
            valid_roles = ", ".join([r.value for r in UserRole])
            print(f"❌ Ошибка: Роли '{role_name}' не существует.")
            print(f"Допустимые роли: {valid_roles}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Использование: python3 scripts/make_admin.py <TELEGRAM_ID> <ROLE>")
        print("Пример: python3 scripts/make_admin.py 12345678 owner")
        sys.exit(1)
        
    target_id = int(sys.argv[1])
    target_role = sys.argv[2]
    
    asyncio.run(set_user_role(target_id, target_role))
