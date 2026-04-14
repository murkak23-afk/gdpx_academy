from __future__ import annotations

import logging
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func
from src.database.session import SessionFactory
from src.database.models.user import User
from src.database.models.submission import Submission
from src.database.models.enums import SubmissionStatus
from src.services.auth_service import AuthService

router = APIRouter(prefix="/nexus", tags=["Nexus"])
logger = logging.getLogger(__name__)

async def get_current_user(request: Request):
    """Проверка авторизации через куки."""
    token = request.cookies.get("nexus_session")
    if not token:
        raise HTTPException(status_code=303, detail="Not authorized")
    
    payload = AuthService.decode_token(token)
    if not payload:
        raise HTTPException(status_code=303, detail="Invalid session")
    
    return payload

@router.get("", response_class=HTMLResponse)
async def get_dashboard(request: Request, user_data: dict = Depends(get_current_user)):
    """Главная страница управления (Dashboard)."""
    from src.api.app import templates
    
    async with SessionFactory() as session:
        # Собираем "Верхние цифры" (Stats)
        # 1. Сток (все PENDING)
        stock_count = await session.scalar(
            select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING)
        ) or 0
        
        # 2. Оборот за сегодня (ACCEPTED)
        from datetime import datetime, timezone, timedelta
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        today_accepted = await session.scalar(
            select(func.count(Submission.id))
            .where(Submission.status == SubmissionStatus.ACCEPTED, Submission.reviewed_at >= today_start)
        ) or 0

        # 3. Количество воркеров
        total_workers = await session.scalar(select(func.count(User.id))) or 0

        stats = {
            "stock": stock_count,
            "today": today_accepted,
            "workers": total_workers
        }

        return templates.TemplateResponse("dashboard.html", {
            "request": request, 
            "user": {"username": user_data.get("sub")},
            "stats": stats
        })

# Обработка редиректа если не авторизован
@router.exception_handler(HTTPException)
async def auth_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 303:
        return RedirectResponse(url="/auth/login")
    return await request.app.default_exception_handler(request, exc)
