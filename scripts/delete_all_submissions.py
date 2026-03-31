#!/usr/bin/env python3
"""
Скрипт для удаления всех заявок (submissions) из базы данных.
ВНИМАНИЕ: Это действие необратимо!

Удаляет:
- Все записи из таблицы submissions
- Все связанные review_actions (каскадно)
- Все связанные publication_archive (каскадно)
"""

import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию проекта в путь
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.publication import PublicationArchive
from src.database.models.submission import ReviewAction, Submission
from src.database.session import SessionFactory


async def count_records(session: AsyncSession) -> dict[str, int]:
    """Подсчитывает количество записей в таблицах."""
    
    submissions_count = (await session.execute(select(func.count(Submission.id)))).scalar_one()
    review_actions_count = (await session.execute(select(func.count(ReviewAction.id)))).scalar_one()
    publications_count = (await session.execute(select(func.count(PublicationArchive.id)))).scalar_one()
    
    return {
        "submissions": submissions_count,
        "review_actions": review_actions_count,
        "publication_archive": publications_count,
    }


async def delete_all_submissions(session: AsyncSession) -> dict[str, int]:
    """Удаляет все заявки и связанные записи."""
    
    # Удаляем submissions (review_actions и publication_archive удалятся каскадно)
    result = await session.execute(delete(Submission))
    submissions_deleted = result.rowcount or 0
    
    await session.commit()
    
    return {
        "submissions_deleted": submissions_deleted,
    }


async def main() -> None:
    """Основная функция."""
    
    print("=" * 70)
    print("УДАЛЕНИЕ ВСЕХ ЗАЯВОК (SUBMISSIONS) ИЗ БАЗЫ ДАННЫХ")
    print("=" * 70)
    print()
    
    async with SessionFactory() as session:
        # Подсчитываем записи до удаления
        print("📊 Подсчёт записей в базе данных...")
        counts_before = await count_records(session)
        
        print(f"\n📋 Текущее состояние базы данных:")
        print(f"   • Submissions (заявки): {counts_before['submissions']}")
        print(f"   • Review Actions (история): {counts_before['review_actions']}")
        print(f"   • Publication Archive (архив): {counts_before['publication_archive']}")
        print()
        
        if counts_before['submissions'] == 0:
            print("✅ База данных уже пуста. Нечего удалять.")
            return
        
        # Запрашиваем подтверждение
        print("⚠️  ВНИМАНИЕ! Это действие необратимо!")
        print("⚠️  Все заявки и связанные данные будут удалены навсегда!")
        print()
        
        confirmation = input("Введите 'ДА' (заглавными буквами) для подтверждения: ")
        
        if confirmation != "ДА":
            print("\n❌ Операция отменена пользователем.")
            return
        
        print("\n🗑️  Удаление записей...")
        result = await delete_all_submissions(session)
        
        # Проверяем результат
        counts_after = await count_records(session)
        
        print(f"\n✅ Удаление завершено!")
        print(f"   • Удалено submissions: {result['submissions_deleted']}")
        print(f"\n📊 Состояние после удаления:")
        print(f"   • Submissions: {counts_after['submissions']}")
        print(f"   • Review Actions: {counts_after['review_actions']}")
        print(f"   • Publication Archive: {counts_after['publication_archive']}")
        print()
        
        if counts_after['submissions'] == 0:
            print("✅ Все записи успешно удалены!")
        else:
            print("⚠️  Внимание: остались записи, которые не были удалены.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n❌ Операция прервана пользователем (Ctrl+C)")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
