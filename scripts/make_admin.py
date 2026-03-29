from __future__ import annotations

import argparse
import asyncio
import socket
import sys
from pathlib import Path

# Чтобы `python scripts/make_admin.py` находил пакет `src` из корня репозитория.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.core.config import get_settings
from src.database.models.enums import UserRole
from src.database.models.user import User


async def promote_role(telegram_id: int, role: UserRole) -> None:
    """Назначает пользователю указанную роль по telegram_id."""

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with session_factory() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user is None:
            print(f"Пользователь с telegram_id={telegram_id} не найден. Сначала зайди в бота через /start.")
            await engine.dispose()
            return

        user.role = role
        await session.commit()
        print(f"Готово: @{user.username or 'без_username'} (telegram_id={telegram_id}) теперь {role.value}.")

    await engine.dispose()


def parse_args() -> argparse.Namespace:
    """Парсит аргументы командной строки."""

    parser = argparse.ArgumentParser(description="Назначить роль пользователю (в т.ч. забрать админку → seller).")
    parser.add_argument("--telegram-id", type=int, required=True, help="Telegram ID пользователя")
    parser.add_argument(
        "--role",
        type=str,
        default=UserRole.CHIEF_ADMIN.value,
        choices=[
            UserRole.SELLER.value,
            UserRole.CHIEF_ADMIN.value,

            UserRole.ADMIN.value,
        ],
        help="Роль: seller — обычный продавец (снять права админа)",
    )
    return parser.parse_args()


def main() -> None:
    """Точка входа CLI-утилиты."""

    args = parse_args()
    try:
        asyncio.run(promote_role(telegram_id=args.telegram_id, role=UserRole(args.role)))
    except socket.gaierror as exc:
        print(
            "Не удаётся разрешить имя хоста PostgreSQL (DNS).\n"
            "Скрипт на хосте не видит имя «postgres» — оно есть только внутри Docker-сети.\n\n"
            "Вариант А — запуск с локальным .env (порт 5432 с хоста):\n"
            "  export ENV_FILE=.env.local\n"
            "  # в .env.local должно быть: POSTGRES_HOST=localhost\n"
            "  python scripts/make_admin.py --telegram-id ...\n\n"
            "Вариант Б — выполнить внутри контейнера бота:\n"
            "  docker compose exec bot python scripts/make_admin.py --telegram-id ...\n",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
