from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func, and_
from sqlalchemy.orm import joinedload
from src.database.session import SessionFactory
from src.database.models.user import User
from src.database.models.submission import Submission
from src.database.models.category import Category
from src.database.models.enums import SubmissionStatus, UserRole
from src.database.models.web_control import SimbuyerPrice
from src.services.auth_service import AuthService

router = APIRouter(prefix="/nexus", tags=["Nexus"])
logger = logging.getLogger(__name__)

async def get_current_user(request: Request):
    token = request.cookies.get("nexus_session")
    if not token:
        raise HTTPException(status_code=303, detail="Not authorized")
    payload = AuthService.decode_token(token)
    if not payload:
        raise HTTPException(status_code=303, detail="Invalid session")
    return payload

@router.get("", response_class=HTMLResponse)
async def get_dashboard(request: Request, user_data: dict = Depends(get_current_user)):
    from src.api.app import templates
    async with SessionFactory() as session:
        user = await session.get(User, user_data.get("user_id"))
        
        # Общая статистика проекта (для Овнера) или личная (для Покупателя)
        stock_count = await session.scalar(select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING)) or 0
        
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # KPI для дашборда
        total_workers = await session.scalar(select(func.count(User.id))) or 0

        return templates.TemplateResponse("dashboard.html", {
            "request": request, 
            "user": user,
            "stats": {"stock": stock_count, "workers": total_workers},
            "active_page": "dashboard"
        })

@router.get("/inventory", response_class=HTMLResponse)
async def get_inventory(request: Request, user_data: dict = Depends(get_current_user)):
    from src.api.app import templates
    async with SessionFactory() as session:
        user = await session.get(User, user_data.get("user_id"))
        
        # Получаем активные категории
        stmt = select(Category).where(Category.is_active == True).order_by(Category.title.asc())
        categories = (await session.execute(stmt)).scalars().all()
        
        # Получаем персональные цены для этого пользователя
        price_stmt = select(SimbuyerPrice).where(SimbuyerPrice.user_id == user.id)
        prices = {p.category_id: p.price for p in (await session.execute(price_stmt)).scalars().all()}
        
        stock_data = {}
        for cat in categories:
            count = await session.scalar(
                select(func.count(Submission.id))
                .where(Submission.category_id == cat.id, Submission.status == SubmissionStatus.PENDING)
            ) or 0
            stock_data[cat.id] = count

        return templates.TemplateResponse("inventory.html", {
            "request": request,
            "user": user,
            "categories": categories,
            "stock": stock_data,
            "custom_prices": prices, # Передаем цены в шаблон
            "active_page": "inventory"
        })

@router.get("/my-esim", response_class=HTMLResponse)
async def get_my_esim(request: Request, user_data: dict = Depends(get_current_user)):
    from src.api.app import templates
    async with SessionFactory() as session:
        user = await session.get(User, user_data.get("user_id"))
        
        stmt = select(Submission).options(joinedload(Submission.category)).where(Submission.status == SubmissionStatus.IN_WORK)
        if user.role == UserRole.SIMBUYER:
            stmt = stmt.where(Submission.delivered_to_chat == user.telegram_id)
            
        active_esims = (await session.execute(stmt.order_by(Submission.updated_at.desc()))).scalars().all()

        return templates.TemplateResponse("my_esim.html", {
            "request": request,
            "user": user,
            "esims": active_esims,
            "active_page": "my-esim"
        })

@router.get("/reports", response_class=HTMLResponse)
async def get_reports(request: Request, user_data: dict = Depends(get_current_user)):
    from src.api.app import templates
    async with SessionFactory() as session:
        user = await session.get(User, user_data.get("user_id"))
        
        # Считаем сводку за сегодня (с 00:00 UTC)
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        base_stmt = select(Submission).where(Submission.updated_at >= today_start)
        if user.role == UserRole.SIMBUYER:
            base_stmt = base_stmt.where(Submission.delivered_to_chat == user.telegram_id)

        # Сбор данных для KPI
        all_today = (await session.execute(base_stmt)).scalars().all()
        
        stats = {
            "total_taken": len(all_today),
            "blocks": len([s for s in all_today if s.status == SubmissionStatus.BLOCKED]),
            "not_scans": len([s for s in all_today if s.status == SubmissionStatus.NOT_A_SCAN]),
            "accepted": len([s for s in all_today if s.status == SubmissionStatus.ACCEPTED]),
            "total_spend": sum([s.purchase_price or 0 for s in all_today if s.status == SubmissionStatus.ACCEPTED])
        }
        
        # Коэффициент успеха
        stats["success_rate"] = round((stats["accepted"] / stats["total_taken"] * 100), 1) if stats["total_taken"] > 0 else 0

        # Список для таблицы (последние 50)
        stmt_list = base_stmt.options(joinedload(Submission.category)).order_by(Submission.updated_at.desc()).limit(50)
        shipments = (await session.execute(stmt_list)).scalars().all()

        return templates.TemplateResponse("reports.html", {
            "request": request,
            "user": user,
            "shipments": shipments,
            "stats": stats,
            "active_page": "reports"
        })

@router.post("/esim/{sub_id}/action/{action}")
async def process_esim_action(sub_id: int, action: str, user_data: dict = Depends(get_current_user)):
    async with SessionFactory() as session:
        user = await session.get(User, user_data.get("user_id"))
        # Запрещаем симбайеру менять статусы!
        if user.role == UserRole.SIMBUYER:
            raise HTTPException(status_code=403, detail="Permission denied")
            
        sub = await session.get(Submission, sub_id)
        if sub:
            if action == "block": sub.status = SubmissionStatus.BLOCKED
            elif action == "not_scan": sub.status = SubmissionStatus.NOT_A_SCAN
            elif action == "accept": sub.status = SubmissionStatus.ACCEPTED
            await session.commit()
        return HTMLResponse(content="")
