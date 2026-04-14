"""FastAPI-приложение: healthcheck и WebApp-хаб. v1.0.2"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, status, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select, func
from aiogram import Dispatcher, Bot
from aiogram.types import Update

from src.core.config import get_settings
from src.database.session import engine, SessionFactory
from src.database.models.category import Category
from src.database.models.submission import Submission
from src.database.models.enums import SubmissionStatus

logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="src/api/templates")

class DeliveryOrder(BaseModel):
    category_id: int
    count: int
    chat_id: int
    init_data: str | None = None # Делаем опциональным

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
                select(
                    Category.id, 
                    Category.title, 
                    Category.is_priority, 
                    func.count(Submission.id).label("stock")
                )
                .outerjoin(Submission, (Submission.category_id == Category.id) & (Submission.status == SubmissionStatus.PENDING))
                .where(Category.is_active == True)
                .group_by(Category.id)
            )
            result = await session.execute(stmt)
            return [
                {"id": r[0], "title": r[1], "is_priority": r[2], "stock": r[3]}
                for r in result.all()
            ]

    @app.post("/api/delivery/order")
    async def process_delivery_order(order: DeliveryOrder, background_tasks: BackgroundTasks):
        """Прием заказа из WebApp и запуск выдачи."""
        async with SessionFactory() as session:
            cat = await session.get(Category, order.category_id)
            if not cat:
                raise HTTPException(status_code=404, detail="Категория не найдена")
            
            if not cat.delivery_thread_id:
                raise HTTPException(status_code=400, detail="Топик для выдачи не настроен для этой категории")
            
            # ЛЕНИВЫЙ ИМПОРТ для предотвращения кругового импорта
            from src.domain.submission.submission_service import SubmissionService
            
            sub_svc = SubmissionService(session=session)
            available = await sub_svc.get_category_stock_count(order.category_id)
            if order.count > available:
                raise HTTPException(status_code=400, detail=f"Недостаточно на складе. Доступно: {available}")

            # Запускаем выдачу в фоне
            background_tasks.add_task(_background_delivery, bot, cat.id, order.chat_id, cat.delivery_thread_id, order.count)
            
            return {"status": "ok"}

    # --- SYSTEM ENDPOINTS ---

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
        
        background_tasks.add_task(dispatcher.feed_update, bot, update)
        return {"ok": True}

    @app.get("/health/ready")
    async def health_ready() -> JSONResponse:
        checks: dict[str, str] = {}
        try:
            async with engine.connect() as conn:
                await conn.execute(select(1))
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {type(exc).__name__}"

        db_ok = checks.get("database") == "ok"
        body = {"status": "ready" if db_ok else "not_ready", "checks": checks}
        return JSONResponse(status_code=200 if db_ok else 503, content=body)

    return app

async def _background_delivery(bot: Bot, category_id: int, chat_id: int, thread_id: int, count: int):
    """Фоновая задача: достает eSIM и шлет в персональный чат и топик категории."""
    # ЛЕНИВЫЕ ИМПОРТЫ
    from src.database.uow import UnitOfWork
    from src.domain.submission.submission_service import SubmissionService
    from src.core.utils.ui_builder import DIVIDER
    from src.database.session import SessionFactory

    async with SessionFactory() as session:
        async with UnitOfWork(session=session) as uow:
            sub_svc = SubmissionService(uow)
            items = await sub_svc.take_from_warehouse(category_id, count)
        
            if not items:
                logger.error(f"Background delivery failed: no items found for cat {category_id}")
                return

            for item in items:
                try:
                    caption = (
                        f"📟 <b>eSIM #{item.id}</b>\n"
                        f"📶 <b>ОПЕРАТОР:</b> {item.category.title}\n"
                        f"📞 <b>НОМЕР:</b> <code>{item.phone_normalized or 'N/A'}</code>\n"
                        f"{DIVIDER}\n"
                        f"👤 <b>АГЕНТ:</b> @{item.seller.username or 'id' + str(item.seller.telegram_id)}"
                    )
                    
                    if item.attachment_type == "photo":
                        await bot.send_photo(
                            chat_id=chat_id, 
                            photo=item.telegram_file_id, 
                            caption=caption, 
                            message_thread_id=thread_id
                        )
                    else:
                        await bot.send_document(
                            chat_id=chat_id, 
                            document=item.telegram_file_id, 
                            caption=caption, 
                            message_thread_id=thread_id
                        )
                    await asyncio.sleep(0.3)
                except Exception as e:
                    logger.error(f"Error in background delivery for item {item.id}: {e}")
