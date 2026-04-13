"""FastAPI-приложение: healthcheck и задел под WebApp."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, status, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy import text
from aiogram import Dispatcher, Bot
from aiogram.types import Update

from src.core.config import get_settings
from src.database.session import engine
from src.domain.finance.cryptobot_service import CryptoBotService

logger = logging.getLogger(__name__)


from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from src.database.models.category import Category
from src.database.models.submission import Submission
from src.database.models.enums import SubmissionStatus, UserRole
from sqlalchemy import select, func
from src.database.session import SessionFactory
from src.domain.submission.submission_service import SubmissionService

logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="src/api/templates")

class DeliveryOrder(BaseModel):
    category_id: int
    count: int
    init_data: str

def create_app(bot: Bot, dispatcher: Dispatcher) -> FastAPI:
    app = FastAPI(
        title="tgpriem API",
        version="1.0.0",
        description="Служебные эндпоинты и Webhook-интеграция.",
    )
    settings = get_settings()

    # --- WEBAPP ENDPOINTS ---

    @app.get("/delivery")
    async def delivery_page(request: Request):
        """Отображение страницы WebApp."""
        return templates.TemplateResponse("delivery.html", {"request": request})

    @app.get("/api/delivery/categories")
    async def get_delivery_categories():
        """Список активных категорий и остатков."""
        async with SessionFactory() as session:
            # Считаем остатки (статус PENDING)
            stmt = (
                select(Category.id, Category.title, Category.is_priority, func.count(Submission.id))
                .outerjoin(Submission, (Submission.category_id == Category.id) & (Submission.status == SubmissionStatus.PENDING))
                .where(Category.is_active == True)
                .group_by(Category.id)
            )
            class DeliveryOrder(BaseModel):
                category_id: int
                count: int
                chat_id: int # Добавляем поле для ID чата
                init_data: str

            def create_app(bot: Bot, dispatcher: Dispatcher) -> FastAPI:
            ...
                @app.post("/api/delivery/order")
                async def process_delivery_order(order: DeliveryOrder, background_tasks: BackgroundTasks):
                    """Прием заказа из WebApp и запуск выдачи."""
                    async with SessionFactory() as session:
                        cat = await session.get(Category, order.category_id)
                        if not cat or not cat.delivery_thread_id:
                            raise HTTPException(status_code=400, detail="Топик для выдачи не настроен")

                        # Проверяем наличие
                        sub_svc = SubmissionService(session=session)
                        available = await sub_svc.get_category_stock_count(order.category_id)
                        if order.count > available:
                            raise HTTPException(status_code=400, detail="Недостаточно на складе")

                        # Передаем order.chat_id в фоновую задачу
                        background_tasks.add_task(_background_delivery, bot, cat.id, order.chat_id, cat.delivery_thread_id, order.count)

                        return {"status": "ok"}
    @app.post(settings.webhook_path)
    async def telegram_webhook(
        request: Request,
        background_tasks: BackgroundTasks,
        x_telegram_bot_api_secret_token: str | None = Header(None),
    ) -> Any:
        """Эндпоинт для приёма обновлений от Telegram."""
        if x_telegram_bot_api_secret_token != settings.webhook_secret_token:
            logger.warning("Unauthorized webhook request with invalid secret token.")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid secret token")

        update_data = await request.json()
        update = Update.model_validate(update_data, context={"bot": bot})
        
        # Передаём обработку в фон, чтобы мгновенно вернуть Telegram {"ok": True}
        background_tasks.add_task(dispatcher.feed_update, bot, update)
        return {"ok": True}

    @app.get("/health")
    async def health_legacy() -> dict[str, str]:
        """Обратная совместимость: только liveness процесса."""

        return {"status": "ok"}

    @app.get("/health/live")
    async def health_live() -> dict[str, str]:
        """Liveness: процесс отвечает (без БД и внешних API)."""

        return {"status": "ok"}

    @app.get("/health/ready")
    async def health_ready() -> JSONResponse:
        """Readiness: БД и опционально Crypto Pay API."""

        checks: dict[str, str] = {}
        settings = get_settings()

        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {type(exc).__name__}"

        crypto_failed = False
        if settings.health_ready_include_cryptobot and settings.crypto_pay_token:
            try:
                await CryptoBotService().get_balance()
                checks["cryptobot"] = "ok"
            except Exception as exc:
                crypto_failed = True
                checks["cryptobot"] = f"error: {type(exc).__name__}"
        else:
            checks["cryptobot"] = "skipped"

        db_ok = checks.get("database") == "ok"
        ready = db_ok and not crypto_failed
        body: dict[str, Any] = {
            "status": "ready" if ready else "not_ready",
            "checks": checks,
        }
        return JSONResponse(status_code=200 if ready else 503, content=body)

    return app

async def _background_delivery(bot: Bot, category_id: int, thread_id: int, count: int):
    """Фоновая задача: достает eSIM и шлет в персональный чат и топик категории."""
    from src.database.uow import UnitOfWork
    from src.domain.submission.submission_service import SubmissionService
    from src.core.utils.ui_builder import DIVIDER
    import asyncio

    async with UnitOfWork() as uow:
        sub_svc = SubmissionService(uow)
        items = await sub_svc.take_from_warehouse(category_id, count)
        
        if not items:
            logger.error(f"Background delivery failed: no items found for cat {category_id}")
            return

        # Берем настройки чата из категории (мы их только что добавили в БД)
        # Если в категории чат не указан, подстрахуемся дефолтным из конфига
        from src.database.models.category import Category
        cat = await uow.session.get(Category, category_id)
        
        from src.core.config import get_settings
        default_chat_id = get_settings().moderation_chat_id
        target_chat_id = cat.delivery_chat_id or default_chat_id

        for item in items:
            try:
                caption = (
                    f"📟 <b>eSIM #{item.id}</b>\n"
                    f"📶 <b>ОПЕРАТОР:</b> {cat.compose_title()}\n"
                    f"📞 <b>НОМЕР:</b> <code>{item.phone_normalized or 'N/A'}</code>\n"
                    f"{DIVIDER}\n"
                    f"👤 <b>АГЕНТ:</b> @{item.owner.username or 'id' + str(item.owner.telegram_id)}"
                )
                
                # Шлем в персональный чат и топик этой категории
                await bot.send_photo(
                    chat_id=target_chat_id, 
                    photo=item.tg_file_id, 
                    caption=caption, 
                    message_thread_id=thread_id
                )
                
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(f"Error in background delivery for item {item.id}: {e}")
