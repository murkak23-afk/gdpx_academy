"""FastAPI-приложение: healthcheck и WebApp-хаб. v1.0.4"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, status, BackgroundTasks
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.exception_handlers import http_exception_handler
from pydantic import BaseModel
from sqlalchemy import select, func
from aiogram import Dispatcher, Bot
from aiogram.types import Update
from pathlib import Path

from src.core.config import get_settings
from src.database.session import engine, SessionFactory
from src.database.models.category import Category
from src.database.models.submission import Submission
from src.database.models.enums import SubmissionStatus

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

class DeliveryOrder(BaseModel):
    category_id: int
    count: int
    chat_id: int
    init_data: str | None = None

def create_app(bot: Bot, dispatcher: Dispatcher) -> FastAPI:
    app = FastAPI(title="tgpriem API", version="1.0.0")
    settings = get_settings()

    # Монтируем статику
    from fastapi.staticfiles import StaticFiles
    app.mount("/assets", StaticFiles(directory=str(BASE_DIR.parent / "presentation" / "assets")), name="assets")

    @app.exception_handler(HTTPException)
    async def auth_exception_handler(request: Request, exc: HTTPException):
        if exc.status_code == 303:
            return RedirectResponse(url="/auth/login")
        return await http_exception_handler(request, exc)

    from src.api.routes import auth, nexus, tickets
    app.include_router(auth.router)
    app.include_router(nexus.router)
    app.include_router(tickets.router)

    @app.get("/delivery")
    async def delivery_page(request: Request):
        return templates.TemplateResponse("delivery.html", {"request": request})

    @app.get("/api/delivery/categories")
    async def get_delivery_categories():
        print("!!! API CALL: get_categories")
        async with SessionFactory() as session:
            stmt = (
                select(Category.id, Category.title, Category.is_priority, func.count(Submission.id))
                .outerjoin(Submission, (Submission.category_id == Category.id) & (Submission.status == SubmissionStatus.PENDING))
                .where(Category.is_active == True)
                .group_by(Category.id)
            )
            result = await session.execute(stmt)
            return [{"id": r[0], "title": r[1], "is_priority": r[2], "stock": r[3]} for r in result.all()]

    @app.post("/api/delivery/order")
    async def process_delivery_order(order: DeliveryOrder, background_tasks: BackgroundTasks):
        # ЭТОТ ПРИНТ ТЫ ДОЛЖЕН УВИДЕТЬ В ЛОГАХ
        print(f"!!! ORDER RECEIVED: Chat={order.chat_id}, Cat={order.category_id}, Count={order.count}")
        
        async with SessionFactory() as session:
            from src.database.models.web_control import DeliveryConfig
            stmt_cfg = select(DeliveryConfig).where(
                DeliveryConfig.category_id == order.category_id,
                DeliveryConfig.chat_id == order.chat_id
            )
            cfg = (await session.execute(stmt_cfg)).scalar_one_or_none()

            if not cfg:
                msg = f"Маршрут не найден. ChatID: {order.chat_id}, CatID: {order.category_id}"
                print(f"!!! ERROR: {msg}")
                raise HTTPException(status_code=400, detail=msg)
            
            from src.domain.submission.submission_service import SubmissionService
            sub_svc = SubmissionService(session=session)
            available = await sub_svc.get_category_stock_count(order.category_id)
            
            if order.count > available:
                raise HTTPException(status_code=400, detail=f"Недостаточно на складе. Доступно: {available}")

            background_tasks.add_task(_background_delivery, bot, cfg.category_id, order.chat_id, cfg.thread_id, order.count)
            return {"status": "ok"}

    @app.post(settings.webhook_path)
    async def telegram_webhook(request: Request, background_tasks: BackgroundTasks, x_tg_token: str | None = Header(None, alias="X-Telegram-Bot-Api-Secret-Token")):
        if x_tg_token != settings.webhook_secret_token:
            raise HTTPException(status_code=401)
        update_data = await request.json()
        update = Update.model_validate(update_data, context={"bot": bot})
        background_tasks.add_task(dispatcher.feed_update, bot, update)
        return {"ok": True}

    return app

async def _background_delivery(bot: Bot, category_id: int, chat_id: int, thread_id: int, count: int):
    from src.database.uow import UnitOfWork
    from src.domain.submission.submission_service import SubmissionService
    from src.core.utils.ui_builder import DIVIDER

    async with SessionFactory() as session:
        async with UnitOfWork(session=session) as uow:
            sub_svc = SubmissionService(uow)
            items = await sub_svc.take_from_warehouse(category_id, count)

            if not items: return

            # Получаем цену для этого чата (покупателя)
            from src.database.models.user import User
            from src.database.models.web_control import SimbuyerPrice
            buyer_stmt = select(User).where(User.telegram_id == chat_id)
            buyer = (await session.execute(buyer_stmt)).scalar_one_or_none()

            price_val = 0
            if buyer:
                price_stmt = select(SimbuyerPrice.price).where(and_(SimbuyerPrice.user_id == buyer.id, SimbuyerPrice.category_id == category_id))
                price_val = (await session.execute(price_stmt)).scalar() or 0

            for item in items:
                # Фиксируем цену покупки
                item.purchase_price = price_val
                item.delivered_to_chat = chat_id
                item.delivered_to_thread = thread_id

                try:
                    caption = (
                        f"📟 <b>eSIM #{item.id}</b>\n"
                        f"📶 <b>ОПЕРАТОР:</b> {item.category.title}\n"
                        f"📞 <b>НОМЕР:</b> <code>{item.phone_normalized or 'N/A'}</code>\n"
                        f"{DIVIDER}\n"
                        f"👤 <b>АГЕНТ:</b> @{item.seller.username or 'id' + str(item.seller.telegram_id)}"
                    )
                    # Шлем в персональный чат
                    await bot.send_photo(
                        chat_id=chat_id, 
                        photo=item.telegram_file_id, 
                        caption=caption, 
                        message_thread_id=thread_id if thread_id != 0 else None
                    )
                    await asyncio.sleep(0.3)
                except Exception as e:
                    print(f"!!! SEND ERROR: {e}")
