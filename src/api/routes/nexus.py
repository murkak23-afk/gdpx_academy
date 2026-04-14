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

from src.database.models.category import Category
from fastapi import Form

@router.get("/inventory", response_class=HTMLResponse)
async def get_inventory(request: Request, user_data: dict = Depends(get_current_user)):
    """Страница управления кластерами."""
    from src.api.app import templates
    async with SessionFactory() as session:
        stmt = select(Category).order_by(Category.is_active.desc(), Category.title.asc())
        result = await session.execute(stmt)
        categories = result.scalars().all()
        
        # Для каждой категории посчитаем текущий сток (PENDING)
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
            "stock": stock_data
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
        
        if field == "payout_rate":
            cat.payout_rate = float(value)
        elif field == "delivery_thread_id":
            cat.delivery_thread_id = int(value) if value else None
        elif field == "delivery_chat_id":
            cat.delivery_chat_id = int(value) if value else None
        
        await session.commit()
        
        # Возвращаем просто текст для HTMX, чтобы подтвердить успех
        return HTMLResponse(content=f'<span class="text-green-500 text-xs animate-pulse">Saved</span>')
