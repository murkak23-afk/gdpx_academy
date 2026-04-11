import asyncio
from sqlalchemy import select, update
from src.database.session import SessionFactory
from src.database.models.submission import Submission
from src.database.models.enums import SubmissionStatus
from src.database.models.user import User

async def recover_lost_items(user_tg_id: int):
    async with SessionFactory() as session:
        # Ищем пользователя
        user = await session.scalar(select(User).where(User.telegram_id == user_tg_id))
        if not user:
            print("❌ Пользователь не найден")
            return

        # Ищем симки в статусе IN_WORK, взятые этим пользователем за последние 10 минут
        stmt = (
            select(Submission)
            .where(
                Submission.admin_id == user.id,
                Submission.status == SubmissionStatus.IN_WORK,
                Submission.is_archived == False
            )
        )
        res = await session.execute(stmt)
        items = list(res.scalars().all())

        if not items:
            print("✅ Нет 'зависших' айтемов для восстановления.")
            return

        print(f"🔄 Найдено {len(items)} зависших айтемов. Возвращаю на склад...")
        
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
        print(f"✅ {len(items)} симок успешно возвращены в буфер (PENDING).")

if __name__ == "__main__":
    asyncio.run(recover_lost_items(7651545773))
