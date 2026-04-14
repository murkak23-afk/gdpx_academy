from __future__ import annotations

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.orm import joinedload
from src.database.session import SessionFactory
from src.database.models.user import User
from src.database.models.submission import Submission
from src.database.models.category import Category
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
        # 1. Сток (все PENDING)
        stock_count = await session.scalar(
            select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING)
        ) or 0
        
        # 2. Оборот за сегодня (ACCEPTED)
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
            "stats": stats,
            "active_page": "dashboard"
        })

@router.get("/reports", response_class=HTMLResponse)
async def get_reports(request: Request, user_data: dict = Depends(get_current_user)):
    """Страница истории отгрузок (отчеты)."""
    from src.api.app import templates
    async with SessionFactory() as session:
        from src.database.models.user import User
        # Ищем пользователя по внутреннему ID из базы (так как он в токене)
        user = await session.get(User, user_data.get("user_id"))
        
        if not user:
            raise HTTPException(status_code=303, detail="User not found")
        
        from src.database.models.submission import Submission
        from src.database.models.enums import UserRole
        
        stmt = select(Submission).options(joinedload(Submission.category), joinedload(Submission.seller))
        
        # Если зашел симбайер — фильтруем только его отгрузки
        if user.role == UserRole.SIMBUYER:
            stmt = stmt.where(Submission.delivered_to_chat == user.telegram_id) # Или другой критерий привязки
        
        stmt = stmt.where(Submission.delivered_to_chat.is_not(None)).order_by(Submission.updated_at.desc()).limit(100)
        
        result = await session.execute(stmt)
        shipments = result.scalars().all()

        return templates.TemplateResponse("reports.html", {
            "request": request,
            "user": {"username": user_data.get("sub")},
            "shipments": shipments,
            "active_page": "reports"
        })

@router.get("/inventory", response_class=HTMLResponse)
async def get_inventory(request: Request, user_data: dict = Depends(get_current_user)):
    """Страница управления кластерами."""
    from src.api.app import templates
    async with SessionFactory() as session:
        stmt = select(Category).order_by(Category.is_active.desc(), Category.title.asc())
        result = await session.execute(stmt)
        categories = result.scalars().all()
        
        stock_data = {}
        for cat in categories:
            count = await session.scalar(
                select(func.count(Submission.id))
                .where(Submission.category_id == cat.id, Submission.status == SubmissionStatus.PENDING)
            ) or 0
            stock_data[cat.id] = count

        return templates.TemplateResponse("inventory.html", {
            "request": request,
            "user": {"username": user_data.get("sub")},
            "categories": categories,
            "stock": stock_data,
            "active_page": "inventory"
        })

@router.post("/inventory/update/{cat_id}")
async def update_category(
    cat_id: int,
    field: str = Form(...),
    value: str = Form(...),
    user_data: dict = Depends(get_current_user)
):
    """Быстрое обновление поля категории через HTMX."""
    async with SessionFactory() as session:
        cat = await session.get(Category, cat_id)
        if not cat:
            raise HTTPException(status_code=404)
        
        try:
            if field == "payout_rate":
                cat.payout_rate = float(value)
            elif field == "delivery_thread_id":
                cat.delivery_thread_id = int(value) if value else None
            elif field == "delivery_chat_id":
                cat.delivery_chat_id = int(value) if value else None
            
            await session.commit()
            return HTMLResponse(content='<span class="text-green-500 text-[10px] font-bold animate-pulse">SAVED</span>')
        except Exception as e:
            logger.error(f"Error updating category {cat_id}: {e}")
            return HTMLResponse(content='<span class="text-red-500 text-[10px] font-bold">ERROR</span>')
