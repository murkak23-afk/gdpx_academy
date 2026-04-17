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

def create_app(bot: Bot, dispatcher: Dispatcher) -> tuple[FastAPI, ConnectionManager]:
    app = FastAPI(title="tgpriem API", version="1.0.0")
    settings = get_settings()
    app.state.bot = bot

    # Монтируем статику
    from fastapi.staticfiles import StaticFiles
    app.mount("/assets", StaticFiles(directory=str(BASE_DIR.parent / "presentation" / "assets")), name="assets")

    @app.middleware("http")
    async def csrf_protect(request: Request, call_next):
        if request.method in ["POST", "PUT", "DELETE", "PATCH"]:
            # Skip check for login (where token is set) and telegram webhooks
            if request.url.path not in ["/auth/login", settings.webhook_path] and not request.url.path.startswith("/api/"):
                cookie_csrf = request.cookies.get("csrftoken")
                header_csrf = request.headers.get("X-CSRF-Token")
                
                # If header is missing, we check if it's a standard form
                # Note: Reading request.form() here can break downstream dependencies.
                # To fix the 'new_role' bug, we must ensure we don't consume the stream prematurely 
                # or we use a more robust way to handle it.
                if not header_csrf and "application/x-www-form-urlencoded" in request.headers.get("Content-Type", ""):
                    # We only check the header for now to avoid body consumption issues in Middleware
                    # Standard forms will work if our JS successfully injects the header (which it should for modern browsers)
                    # or if we move CSRF check to a dependency.
                    pass 
                
                if not cookie_csrf or (header_csrf and cookie_csrf != header_csrf):
                    # If cookie exists but header is present and doesn't match
                    return JSONResponse(status_code=403, content={"detail": "CSRF Token invalid"})
                
                if not cookie_csrf or not header_csrf:
                    # If either is missing for a state-changing request
                    # For now, allow if header is missing but it's NOT an HTMX request to prevent breaking legacy forms
                    if request.headers.get("HX-Request"):
                        return JSONResponse(status_code=403, content={"detail": "CSRF Token missing"})
        
        response = await call_next(request)
        
        # Set a new CSRF token cookie if not present
        if not request.cookies.get("csrftoken"):
            import secrets
            response.set_cookie("csrftoken", secrets.token_hex(32), httponly=False, samesite="lax")
            
        return response

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.exception_handler(HTTPException)
    async def auth_exception_handler(request: Request, exc: HTTPException):
        if exc.status_code == 303:
            return RedirectResponse(url="/auth/login")
        return await http_exception_handler(request, exc)

    from src.api.routes import auth, gdpx, tickets
    app.include_router(auth.router)
    app.include_router(gdpx.router)
    app.include_router(tickets.router)

    from fastapi import WebSocket, WebSocketDisconnect

    class ConnectionManager:
        def __init__(self):
            self.active_connections: list[WebSocket] = []

        async def connect(self, websocket: WebSocket):
            await websocket.accept()
            self.active_connections.append(websocket)

        def disconnect(self, websocket: WebSocket):
            self.active_connections.remove(websocket)

        async def broadcast(self, message: dict):
            for connection in self.active_connections:
                await connection.send_json(message)

    manager = ConnectionManager()
    app.state.ws_manager = manager

    @app.websocket("/gdpx/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text() # Keep connection alive
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    from src.services.delivery_service import background_delivery_task

    @app.get("/")
    async def root_redirect():
        return RedirectResponse(url="/auth/login")

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

            background_tasks.add_task(background_delivery_task, bot, cfg.category_id, order.chat_id, cfg.thread_id, order.count, manager)
            return {"status": "ok"}

    @app.post(settings.webhook_path)
    async def telegram_webhook(request: Request, background_tasks: BackgroundTasks, x_tg_token: str | None = Header(None, alias="X-Telegram-Bot-Api-Secret-Token")):
        if x_tg_token != settings.webhook_secret_token:
            raise HTTPException(status_code=401)
        update_data = await request.json()
        update = Update.model_validate(update_data, context={"bot": bot})
        background_tasks.add_task(dispatcher.feed_update, bot, update)
        return {"ok": True}

    return app, manager
