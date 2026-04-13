from sqlalchemy import select, text, update

from src.database.models.enums import SubmissionStatus, UserRole
from src.database.models.submission import Submission
from src.database.models.user import User
from src.database.session import SessionFactory


async def set_user_role(tg_id: int, role_name: str):
    async with SessionFactory() as session:
        stmt = select(User).where(User.telegram_id == tg_id)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()
        
        if not user:
            print(f"❌ Пользователь с TG ID {tg_id} не найден!")
            return

        try:
            new_role = UserRole(role_name.lower())
            user.role = new_role
            await session.commit()
            print(f"✅ Роль пользователя @{user.username or user.telegram_id} изменена на: {new_role.value}")
        except ValueError:
            valid_roles = ", ".join([r.value for r in UserRole])
            print(f"❌ Ошибка: Роли '{role_name}' не существует. Допустимые: {valid_roles}")

async def unblock_all():
    async with SessionFactory() as session:
        stmt = (
            update(User)
            .values(
                is_restricted=False,
                duplicate_timeout_until=None,
                captcha_attempts=0
            )
        )
        result = await session.execute(stmt)
        await session.commit()
        print(f"✅ Глобальный сброс ограничений выполнен для {result.rowcount} пользователей.")

async def fix_roles():
    async with SessionFactory() as session:
        # Обновляем старую роль 'simbuy' на 'seller'
        result = await session.execute(
            text("UPDATE users SET role = 'seller' WHERE role = 'simbuy'")
        )
        await session.commit()
        print(f"✅ Исправлено строк: {result.rowcount}")

async def recover_lost_items(user_tg_id: int):
    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.telegram_id == user_tg_id))
        if not user:
            print("❌ Пользователь не найден")
            return

        stmt = (
            select(Submission)
            .where(
                Submission.admin_id == user.id,
                Submission.status == SubmissionStatus.IN_WORK,
                not Submission.is_archived
            )
        )
        res = await session.execute(stmt)
        items = list(res.scalars().all())

        if not items:
            print("✅ Нет 'зависших' айтемов для восстановления.")
            return

        ids = [i.id for i in items]
        await session.execute(
            update(Submission)
            .where(Submission.id.in_(ids))
            .values(
                status=SubmissionStatus.PENDING,
                admin_id=None,
                assigned_at=None
            )
        )
        await session.commit()
        print(f"✅ {len(items)} симок возвращены в буфер (PENDING).")
