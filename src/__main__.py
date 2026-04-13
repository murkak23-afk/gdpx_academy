import asyncio
import logging
import sys

try:
    import uvloop
    uvloop.install()
except ImportError:
    pass

import typer

from src.core.app import run_application

app = typer.Typer(help="GDPX Bot CLI")

def _configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(handler)

@app.command()
def start():
    """Запуск бота и API (uvicorn)."""
    _configure_logging()
    log = logging.getLogger(__name__)
    log.info("Старт процесса (бот + HTTP)")
    try:
        asyncio.run(run_application())
    except KeyboardInterrupt:
        log.info("Остановка по KeyboardInterrupt")
    finally:
        log.info("Процесс завершён")

@app.command()
def worker():
    """Запуск ARQ воркера."""
    _configure_logging()
    from src.core.app import run_worker
    asyncio.run(run_worker())

@app.command()
def make_admin(tg_id: int, role: str):
    """Смена роли пользователя по Telegram ID."""
    from tools.admin import set_user_role
    asyncio.run(set_user_role(tg_id, role))

@app.command()
def unblock_users():
    """Сброс всех ограничений (is_restricted, капча) для всех пользователей."""
    from tools.admin import unblock_all
    asyncio.run(unblock_all())

@app.command()
def fix_legacy_roles():
    """Миграция ролей (simbuy -> seller)."""
    from tools.admin import fix_roles
    asyncio.run(fix_roles())

@app.command()
def recover_items(tg_id: int):
    """Восстановление зависших айтемов у модератора (в статус PENDING)."""
    from tools.admin import recover_lost_items
    asyncio.run(recover_lost_items(tg_id))

if __name__ == "__main__":
    app()
