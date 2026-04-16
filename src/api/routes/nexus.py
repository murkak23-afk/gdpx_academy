from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from decimal import Decimal
import io
import csv

from fastapi import APIRouter, Request, Depends, HTTPException, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select, func, and_, or_, String
from sqlalchemy.orm import joinedload

from src.database.session import SessionFactory
from src.database.models.user import User
from src.database.models.submission import Submission
from src.database.models.category import Category
from src.database.models.enums import SubmissionStatus, UserRole
from src.database.models.web_control import SimbuyerPrice, SupportTicket, ChatMessage, DeliveryConfig, WebAccount
from src.database.models.admin_audit import AdminAuditLog
from src.api.deps import templates, get_current_user, RoleChecker, get_db, get_bot
from src.core.utils.audit_logger import log_admin_action
from aiogram import Bot
from src.services.delivery_service import background_delivery_task
from src.domain.submission.submission_service import SubmissionService

router = APIRouter(prefix="/nexus", tags=["Nexus"])
logger = logging.getLogger(__name__)

# RBAC Dependencies
admin_only = RoleChecker([UserRole.OWNER, UserRole.ADMIN])
owner_only = RoleChecker([UserRole.OWNER])

@router.get("/media/{file_id}")
async def get_media_proxy(file_id: str, user: User = Depends(get_current_user), bot: Bot = Depends(get_bot)):
    """Прокси для отображения фото из Telegram по file_id."""
    try:
        file = await bot.get_file(file_id)
        dest = io.BytesIO()
        await bot.download_file(file.file_path, destination=dest)
        dest.seek(0)
        return StreamingResponse(dest, media_type="image/jpeg")
    except Exception as e:
        logger.error(f"Failed to proxy media {file_id}: {e}")
        return HTMLResponse(content="Media error", status_code=404)

@router.get("/users/blacklist", response_class=HTMLResponse)
async def get_blacklist(request: Request, user: User = Depends(admin_only)):
    """Просмотр заблокированных пользователей."""
    async with SessionFactory() as session:
        stmt = select(User).where(User.is_active == False).order_by(User.updated_at.desc())
        blocked_users = (await session.execute(stmt)).scalars().all()
        
        return templates.TemplateResponse("users_manage.html", {
            "request": request,
            "user": user,
            "all_users": blocked_users,
            "roles": [r.value for r in UserRole],
            "active_page": "users",
            "is_blacklist_view": True
        })

@router.post("/users/{target_id}/toggle-active")
async def toggle_user_active(target_id: int, user: User = Depends(admin_only)):
    """Блокировка/разблокировка пользователя."""
    async with SessionFactory() as session:
        target = await session.get(User, target_id)
        if target:
            if target.id == user.id:
                raise HTTPException(status_code=400, detail="Cannot block yourself")
                
            target.is_active = not target.is_active
            await session.commit()
            
            await log_admin_action(
                admin_id=user.id,
                action="BLOCK_USER" if not target.is_active else "UNBLOCK_USER",
                target_type="user",
                target_id=target.id,
                details=f"Статус изменен на {'BLOCKED' if not target.is_active else 'ACTIVE'}"
            )
            return HTMLResponse(content='<script>window.location.reload();</script>')
        return HTTPException(status_code=404)
@router.get("", response_class=HTMLResponse)
async def get_dashboard(request: Request, user: User = Depends(get_current_user)):
    async with SessionFactory() as session:
        # Общий склад (видят ВСЕ)
        stock_count = await session.scalar(select(func.count(Submission.id)).where(Submission.status == SubmissionStatus.PENDING)) or 0
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        if user.role in [UserRole.OWNER, UserRole.ADMIN]:
            # Общая статистика проекта для ADMIN/OWNER
            today_stmt = select(Submission).where(Submission.updated_at >= today_start, Submission.status == SubmissionStatus.ACCEPTED)
            today_subs = (await session.execute(today_stmt)).scalars().all()
            
            stats = {
                "stock": stock_count, 
                "workers": await session.scalar(select(func.count(User.id))) or 0,
                "today_count": len(today_subs),
                "today_amount": sum([s.purchase_price or 0 for s in today_subs])
            }
        else:
            # Личная статистика для SIMBUYER
            base_stmt = select(Submission).where(Submission.delivered_to_chat == user.telegram_id, Submission.updated_at >= today_start)
            user_today_subs = (await session.execute(base_stmt)).scalars().all()
            
            stats = {
                "stock": stock_count, 
                "workers": 0,
                "today_count": len(user_today_subs),
                "today_amount": sum([s.purchase_price or 0 for s in user_today_subs if s.status == SubmissionStatus.ACCEPTED])
            }

        return templates.TemplateResponse("dashboard.html", {
            "request": request, 
            "user": user,
            "stats": stats,
            "active_page": "dashboard"
        })

@router.get("/inventory", response_class=HTMLResponse)
async def get_inventory(request: Request, user: User = Depends(get_current_user)):
    async with SessionFactory() as session:
        # Получаем активные категории
        stmt = select(Category).where(Category.is_active == True).order_by(Category.title.asc())
        categories = (await session.execute(stmt)).scalars().all()
        
        # Получаем персональные цены для этого пользователя
        price_stmt = select(SimbuyerPrice).where(SimbuyerPrice.user_id == user.id)
        custom_prices_raw = (await session.execute(price_stmt)).scalars().all()
        prices = {p.category_id: p.price for p in custom_prices_raw}
        
        # Заполняем пропуски базовыми ценами категорий
        for cat in categories:
            if cat.id not in prices:
                prices[cat.id] = cat.payout_rate

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
            "custom_prices": prices,
            "active_page": "inventory"
        })

@router.get("/my-esim", response_class=HTMLResponse)
async def get_my_esim(request: Request, user: User = Depends(get_current_user)):
    async with SessionFactory() as session:
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

@router.post("/esim/batch-action/{action}")
async def process_esim_batch_action(
    action: str, 
    ids: str = Form(...), 
    user: User = Depends(get_current_user)
):
    """Массовая обработка eSIM (например, массовый зачёт)."""
    async with SessionFactory() as session:
        if user.role not in [UserRole.OWNER, UserRole.ADMIN]:
            raise HTTPException(status_code=403)
            
        try:
            target_ids = [int(i) for i in ids.split(",") if i.strip()]
        except ValueError:
            return HTMLResponse(content="Invalid IDs")

        if not target_ids:
            return HTMLResponse(content="No IDs selected")

        stmt = select(Submission).where(Submission.id.in_(target_ids))
        items = (await session.execute(stmt)).scalars().all()
        
        count = 0
        for item in items:
            old_status = item.status
            new_status = None
            
            if action == "accept": new_status = SubmissionStatus.ACCEPTED
            elif action == "block": new_status = SubmissionStatus.BLOCKED
            elif action == "not_scan": new_status = SubmissionStatus.NOT_A_SCAN
            
            if new_status and old_status != new_status:
                item.status = new_status
                item.reviewed_at = datetime.now(timezone.utc)
                count += 1
                
                # Пишем в лог модерации
                from src.database.models.submission import ReviewAction
                action_log = ReviewAction(
                    submission_id=item.id,
                    admin_id=user.id,
                    from_status=old_status,
                    to_status=new_status,
                    comment="Массовая обработка через веб-панель"
                )
                session.add(action_log)

        if count > 0:
            await session.commit()
            await log_admin_action(
                admin_id=user.id,
                action=f"BATCH_{action.upper()}",
                target_type="submission",
                target_id=0,
                details=f"Массово обработано {count} шт."
            )

        return HTMLResponse(content=f'<script>window.location.reload();</script>')

@router.get("/reports", response_class=HTMLResponse)
async def get_reports(request: Request, user: User = Depends(get_current_user)):
    async with SessionFactory() as session:
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        base_stmt = select(Submission).where(Submission.updated_at >= today_start)
        if user.role == UserRole.SIMBUYER:
            base_stmt = base_stmt.where(Submission.delivered_to_chat == user.telegram_id)

        all_today = (await session.execute(base_stmt)).scalars().all()
        
        stats = {
            "total_taken": len([s for s in all_today if s.status != SubmissionStatus.PENDING]),
            "blocks": len([s for s in all_today if s.status == SubmissionStatus.BLOCKED]),
            "not_scans": len([s for s in all_today if s.status == SubmissionStatus.NOT_A_SCAN]),
            "accepted": len([s for s in all_today if s.status == SubmissionStatus.ACCEPTED]),
            "total_spend": sum([s.purchase_price or 0 for s in all_today if s.status == SubmissionStatus.ACCEPTED])
        }
        
        stats["success_rate"] = round((stats["accepted"] / stats["total_taken"] * 100), 1) if stats["total_taken"] > 0 else 0

        stmt_list = base_stmt.options(joinedload(Submission.category)).order_by(Submission.updated_at.desc()).limit(500)
        shipments = (await session.execute(stmt_list)).scalars().all()

        return templates.TemplateResponse("reports.html", {
            "request": request,
            "user": user,
            "shipments": shipments,
            "stats": stats,
            "active_page": "reports"
        })

@router.get("/reports/export")
async def export_reports_csv(user: User = Depends(admin_only)):
    """Выгрузка отчетов в CSV."""
    async with SessionFactory() as session:
        stmt = select(Submission).options(joinedload(Submission.category)).order_by(Submission.updated_at.desc())
        items = (await session.execute(stmt)).scalars().all()
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Phone", "Category", "Status", "Price", "Date"])
        
        for i in items:
            writer.writerow([i.id, i.phone_normalized or 'N/A', i.category.title, i.status, i.purchase_price or 0, i.updated_at.strftime('%Y-%m-%d %H:%M')])
            
        response = StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv"
        )
        response.headers["Content-Disposition"] = "attachment; filename=gdpx_reports.csv"
        return response

@router.get("/submission/{sub_id}", response_class=HTMLResponse)
async def view_submission(sub_id: int, request: Request, user: User = Depends(get_current_user)):
    """Детальная страница одной eSIM (скана)."""
    async with SessionFactory() as session:
        # Базовая выборка с категорией
        stmt = select(Submission).options(joinedload(Submission.category)).where(Submission.id == sub_id)
        
        # Загружаем продавца только для админов и овнера (Изоляция данных)
        if user.role in [UserRole.OWNER, UserRole.ADMIN]:
            stmt = stmt.options(joinedload(Submission.seller))
            
        res = await session.execute(stmt)
        sub = res.scalar_one_or_none()
        
        if not sub:
            raise HTTPException(status_code=404, detail="eSIM не найдена")

        if user.role == UserRole.SIMBUYER and sub.delivered_to_chat != user.telegram_id:
            raise HTTPException(status_code=403, detail="Доступ запрещен")

        return templates.TemplateResponse("submission_detail.html", {
            "request": request,
            "user": user,
            "sub": sub,
            "active_page": "reports"
        })

@router.get("/categories", response_class=HTMLResponse)
async def get_categories_manage(request: Request, user: User = Depends(admin_only)):
    """Страница управления категориями."""
    async with SessionFactory() as session:
        stmt = select(Category).order_by(Category.is_priority.desc(), Category.title.asc())
        categories = (await session.execute(stmt)).scalars().all()
        
        stock_data = {}
        for cat in categories:
            count = await session.scalar(
                select(func.count(Submission.id))
                .where(Submission.category_id == cat.id, Submission.status == SubmissionStatus.PENDING)
            ) or 0
            stock_data[cat.id] = count

        return templates.TemplateResponse("categories_manage.html", {
            "request": request,
            "user": user,
            "categories": categories,
            "stock": stock_data,
            "active_page": "categories"
        })

@router.post("/categories/{cat_id}/toggle")
async def toggle_category(cat_id: int, user: User = Depends(admin_only)):
    """HTMX-переключатель активности категории."""
    async with SessionFactory() as session:
        cat = await session.get(Category, cat_id)
        if cat:
            cat.is_active = not cat.is_active
            await session.commit()
            
            status_text = "ACTIVE" if cat.is_active else "INACTIVE"
            status_color = "text-nexus-cyan border-nexus-cyan/30 bg-nexus-cyan/10 shadow-[0_0_10px_rgba(0,217,255,0.1)]" if cat.is_active else "text-white/20 border-white/5 bg-white/5"
            return HTMLResponse(content=f'<span class="px-3 py-1 text-[10px] border rounded-lg uppercase tracking-widest font-bold {status_color}">{status_text}</span>')
        return HTMLResponse(content="Error")

@router.post("/categories/{cat_id}/price")
async def update_category_price(cat_id: int, price: Decimal = Form(...), user: User = Depends(admin_only)):
    """Обновление базовой цены категории."""
    async with SessionFactory() as session:
        cat = await session.get(Category, cat_id)
        if cat:
            old_price = cat.payout_rate
            cat.payout_rate = price
            await session.commit()
            
            await log_admin_action(
                admin_id=user.id,
                action="UPDATE_PRICE",
                target_type="category",
                target_id=cat.id,
                details=f"Цена изменена: {old_price} -> {price}"
            )
            return RedirectResponse(url="/nexus/categories", status_code=303)
        return HTTPException(status_code=404)

@router.post("/categories/create")
async def create_category(
    title: str = Form(...),
    slug: str = Form(...),
    payout_rate: Decimal = Form(...),
    user: User = Depends(admin_only)
):
    """Создание новой категории активов."""
    async with SessionFactory() as session:
        new_cat = Category(
            title=title,
            slug=slug,
            payout_rate=payout_rate,
            is_active=True
        )
        session.add(new_cat)
        await session.commit()
        await log_admin_action(admin_id=user.id, action="CREATE_CATEGORY", target_type="category", target_id=new_cat.id, details=f"Создана кат. {title} (slug: {slug})")
        return RedirectResponse(url="/nexus/categories", status_code=303)

@router.post("/categories/{cat_id}/update")
async def update_category(
    cat_id: int,
    title: str = Form(...),
    payout_rate: Decimal = Form(...),
    user: User = Depends(admin_only)
):
    """Обновление существующей категории."""
    async with SessionFactory() as session:
        cat = await session.get(Category, cat_id)
        if cat:
            cat.title = title
            cat.payout_rate = payout_rate
            await session.commit()
            await log_admin_action(admin_id=user.id, action="UPDATE_CATEGORY", target_type="category", target_id=cat.id, details=f"Обновлена кат. {title}, цена {payout_rate}")
            return RedirectResponse(url="/nexus/categories", status_code=303)
        return HTTPException(status_code=404)

@router.get("/users/{target_id}/delivery", response_class=HTMLResponse)
async def get_user_delivery_settings(target_id: int, request: Request, user: User = Depends(admin_only)):
    """Страница настройки персональных маршрутов выдачи пользователя."""
    async with SessionFactory() as session:
        target = await session.get(User, target_id)
        if not target:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
            
        stmt = select(DeliveryConfig).options(joinedload(DeliveryConfig.category)).where(DeliveryConfig.user_id == target.id)
        configs = (await session.execute(stmt)).scalars().all()
        categories = (await session.execute(select(Category).where(Category.is_active == True))).scalars().all()
        
        return templates.TemplateResponse("user_delivery_settings.html", {
            "request": request,
            "user": user,
            "target": target,
            "configs": configs,
            "categories": categories,
            "active_page": "users"
        })

@router.post("/users/{target_id}/delivery/add")
async def add_user_delivery_config(
    target_id: int, 
    category_id: int = Form(...), 
    chat_id: int = Form(...), 
    thread_id: int = Form(...),
    user: User = Depends(admin_only)
):
    """Добавление нового маршрута выдачи для пользователя."""
    async with SessionFactory() as session:
        new_cfg = DeliveryConfig(
            user_id=target_id,
            category_id=category_id,
            chat_id=chat_id,
            thread_id=thread_id
        )
        session.add(new_cfg)
        await session.commit()
        
        await log_admin_action(
            admin_id=user.id,
            action="ADD_DELIVERY_ROUTE",
            target_type="user",
            target_id=target_id,
            details=f"Добавлен маршрут: Cat={category_id}, Chat={chat_id}, Thread={thread_id}"
        )
        
        return RedirectResponse(url=f"/nexus/users/{target_id}/delivery", status_code=303)

@router.post("/users/delivery/{cfg_id}/delete")
async def delete_delivery_config(cfg_id: int, user: User = Depends(admin_only)):
    """Удаление маршрута выдачи."""
    async with SessionFactory() as session:
        cfg = await session.get(DeliveryConfig, cfg_id)
        if cfg:
            target_id = cfg.user_id
            await session.delete(cfg)
            await session.commit()
            return RedirectResponse(url=f"/nexus/users/{target_id}/delivery", status_code=303)
        return HTTPException(status_code=404)

@router.get("/users/{target_id}/prices", response_class=HTMLResponse)
async def get_user_prices_settings(target_id: int, request: Request, user: User = Depends(get_current_user)):
    """Страница настройки персональных цен пользователя."""

    async with SessionFactory() as session:
        if user.role not in [UserRole.OWNER, UserRole.ADMIN]:            raise HTTPException(status_code=403, detail="Permission denied")
            
        target = await session.get(User, target_id)
        if not target:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
            
        from src.database.models.web_control import SimbuyerPrice
        stmt = select(SimbuyerPrice).options(joinedload(SimbuyerPrice.category)).where(SimbuyerPrice.user_id == target.id)
        prices = (await session.execute(stmt)).scalars().all()
        
        # Список категорий
        categories = (await session.execute(select(Category).where(Category.is_active == True))).scalars().all()
        
        return templates.TemplateResponse("user_prices_settings.html", {
            "request": request,
            "user": user,
            "target": target,
            "prices": prices,
            "categories": categories,
            "active_page": "users"
        })

@router.post("/users/{target_id}/prices/add")
async def add_user_price_config(
    target_id: int,
    category_id: int = Form(...),
    price: Decimal = Form(...),
    user: User = Depends(get_current_user)
):
    """Добавление/обновление персональной цены."""
    async with SessionFactory() as session:
        if user.role not in [UserRole.OWNER, UserRole.ADMIN]:            raise HTTPException(status_code=403, detail="Permission denied")
            
        from src.database.models.web_control import SimbuyerPrice
        # Ищем, нет ли уже цены для этой категории
        stmt = select(SimbuyerPrice).where(SimbuyerPrice.user_id == target_id, SimbuyerPrice.category_id == category_id)
        existing = (await session.execute(stmt)).scalar_one_or_none()
        
        if existing:
            existing.price = price
        else:
            new_price = SimbuyerPrice(user_id=target_id, category_id=category_id, price=price)
            session.add(new_price)
            
        await session.commit()
        await log_admin_action(admin_id=user.id, action="UPDATE_USER_PRICE", target_type="user", target_id=target_id, details=f"Установлена цена {price} для кат. {category_id}")
        return RedirectResponse(url=f"/nexus/users/{target_id}/prices", status_code=303)

@router.post("/users/prices/{price_id}/delete")
async def delete_user_price(price_id: int, user: User = Depends(get_current_user)):
    """Удаление персональной цены."""
    async with SessionFactory() as session:
        if user.role not in [UserRole.OWNER, UserRole.ADMIN]:
            raise HTTPException(status_code=403, detail="Permission denied")
            
        from src.database.models.web_control import SimbuyerPrice
        price_cfg = await session.get(SimbuyerPrice, price_id)
        if price_cfg:
            target_id = price_cfg.user_id
            await session.delete(price_cfg)
            await session.commit()
            return RedirectResponse(url=f"/nexus/users/{target_id}/prices", status_code=303)
        return HTTPException(status_code=404)

from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
import io

@router.get("/media/{file_id}")
async def get_media_proxy(file_id: str, user: User = Depends(get_current_user), bot: Bot = Depends(get_bot)):
    """Прокси для отображения фото из Telegram по file_id."""
    try:
        file = await bot.get_file(file_id)
        # Скачиваем файл в память
        dest = io.BytesIO()
        await bot.download_file(file.file_path, destination=dest)
        dest.seek(0)
        return StreamingResponse(dest, media_type="image/jpeg")
    except Exception as e:
        logger.error(f"Failed to proxy media {file_id}: {e}")
        return HTMLResponse(content="Media error", status_code=404)

@router.get("/users/blacklist", response_class=HTMLResponse)
async def get_blacklist(request: Request, user: User = Depends(get_current_user)):
    """Просмотр заблокированных пользователей."""
    async with SessionFactory() as session:
        if user.role not in [UserRole.OWNER, UserRole.ADMIN]:
            raise HTTPException(status_code=403, detail="Permission denied")
            
        stmt = select(User).where(User.is_active == False).order_by(User.updated_at.desc())
        blocked_users = (await session.execute(stmt)).scalars().all()
        
        return templates.TemplateResponse("users_manage.html", {
            "request": request,
            "user": user,
            "all_users": blocked_users,
            "roles": [r.value for r in UserRole],
            "active_page": "users",
            "is_blacklist_view": True
        })

@router.post("/users/{target_id}/toggle-active")
async def toggle_user_active(target_id: int, user: User = Depends(get_current_user)):
    """Блокировка/разблокировка пользователя."""
    async with SessionFactory() as session:
        if user.role not in [UserRole.OWNER, UserRole.ADMIN]:
            raise HTTPException(status_code=403, detail="Permission denied")
            
        target = await session.get(User, target_id)
        if target:
            if target.id == user.id:
                raise HTTPException(status_code=400, detail="Cannot block yourself")
                
            target.is_active = not target.is_active
            await session.commit()
            
            await log_admin_action(
                admin_id=user.id,
                action="BLOCK_USER" if not target.is_active else "UNBLOCK_USER",
                target_type="user",
                target_id=target.id,
                details=f"Статус изменен на {'BLOCKED' if not target.is_active else 'ACTIVE'}"
            )
            return HTMLResponse(content='<script>window.location.reload();</script>')
        return HTTPException(status_code=404)

from src.services.delivery_service import background_delivery_task

@router.post("/inventory/take", response_class=HTMLResponse)
async def take_esim_from_inventory(
    background_tasks: BackgroundTasks,
    category_id: int = Form(...),
    count: int = Form(1),
    user: User = Depends(get_current_user),
    bot: Bot = Depends(get_bot)
):
    """Выдача eSIM из инвентаря для симбайера."""
    async with SessionFactory() as session:
        
        # 1. Ищем конфигурацию доставки (персональный чат/топик симбайера)
        from src.database.models.web_control import DeliveryConfig
        stmt_cfg = select(DeliveryConfig).where(
            DeliveryConfig.category_id == category_id,
            DeliveryConfig.user_id == user.id
        )
        cfg = (await session.execute(stmt_cfg)).scalar_one_or_none()

        if not cfg:
            return HTMLResponse(content='<div class="text-red-400 p-4 bg-red-900/20 border border-red-900 rounded-lg text-sm">Нет настроенного маршрута (DeliveryConfig). Обратитесь к OWNER.</div>')

        # 2. Проверяем наличие
        from src.domain.submission.submission_service import SubmissionService
        sub_svc = SubmissionService(session=session)
        available = await sub_svc.get_category_stock_count(category_id)
        
        if count > available:
            return HTMLResponse(content=f'<div class="text-amber-400 p-4 bg-amber-900/20 border border-amber-900 rounded-lg text-sm">Недостаточно на складе.</div>')

        # 3. Запускаем общую задачу выдачи
        background_tasks.add_task(background_delivery_task, bot, category_id, user.id, cfg.chat_id, cfg.thread_id, count)
        
        # Логируем
        await log_admin_action(
            admin_id=user.id,
            action="TAKE_ESIM_WEB",
            target_type="category",
            target_id=category_id,
            details=f"Запрос {count} шт. -> Чат {cfg.chat_id}"
        )
        
        return HTMLResponse(content='<script>window.location.href="/nexus/my-esim"</script>')

@router.post("/submission/{sub_id}/show-in-bot")
async def show_in_bot(sub_id: int, user: User = Depends(get_current_user), bot: Bot = Depends(get_bot)):
    """Отправка карточки сим-карты в личку админу/овнеру в телеграм."""
    async with SessionFactory() as session:
        if user.role not in [UserRole.OWNER, UserRole.ADMIN]:
            raise HTTPException(status_code=403)
            
        stmt = select(Submission).options(
            joinedload(Submission.category), 
            joinedload(Submission.seller)
        ).where(Submission.id == sub_id)
        sub = (await session.execute(stmt)).scalar_one_or_none()
        
        if not sub:
            return HTMLResponse(content="Not Found")

        text = (
            f"🔍 *ДЕТАЛИ СИМ-КАРТЫ #{sub.id}*\n\n"
            f"📱 Номер: `{sub.phone_normalized or 'Н/Д'}`\n"
            f"🏷 Категория: *{sub.category.title}*\n"
            f"⚙️ Статус: `{sub.status.upper()}`\n\n"
            f"👤 Продавец: @{sub.seller.username or 'unknown'} (`{sub.seller.telegram_id}`)\n"
            f"📅 Создана: {sub.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        )
        
        try:
            await bot.send_message(user.telegram_id, text, parse_mode="Markdown")
            return HTMLResponse(content='<span class="text-[10px] text-emerald-400 font-bold uppercase tracking-widest">Отправлено в бот ✅</span>')
        except Exception as e:
            logger.error(f"Failed to send card to {user.telegram_id}: {e}")
            return HTMLResponse(content='<span class="text-[10px] text-red-400 font-bold uppercase tracking-widest">Ошибка отправки ❌</span>')

@router.get("/submission/{sub_id}/discuss")
async def discuss_submission(sub_id: int, user: User = Depends(get_current_user)):
    """Переход в чат обсуждения конкретной сим-карты (создает тикет, если его нет)."""
    async with SessionFactory() as session:
        # 1. Ищем саму симку        sub = await session.get(Submission, sub_id)
        if not sub:
            raise HTTPException(status_code=404, detail="eSIM не найдена")

        # 2. Ищем существующий открытый тикет для этой симки
        from src.database.models.web_control import SupportTicket
        stmt = select(SupportTicket).where(
            SupportTicket.submission_id == sub_id,
            SupportTicket.status == "open"
        )
        ticket = (await session.execute(stmt)).scalar_one_or_none()

        if not ticket:
            # 3. Создаем новый тикет, если обсуждение еще не начато
            ticket = SupportTicket(
                creator_id=user.id,
                submission_id=sub_id,
                category_id=sub.category_id,
                subject=f"Обсуждение eSIM #{sub_id}",
                status="open"
            )
            session.add(ticket)
            await session.commit()
            await session.refresh(ticket)
            
            # Пишем аудит-лог
            await log_admin_action(
                admin_id=user.id,
                action="START_DISCUSSION",
                target_type="submission",
                target_id=sub_id,
                details=f"Начато обсуждение в тикете #{ticket.id}"
            )

        return RedirectResponse(url=f"/nexus/tickets/{ticket.id}", status_code=303)

@router.get("/users", response_class=HTMLResponse)
async def get_users_manage(request: Request, q: Optional[str] = None, user: User = Depends(get_current_user)):
    """Страница управления пользователями (для OWNER и ADMIN)."""

    async with SessionFactory() as session:
        if user.role not in [UserRole.OWNER, UserRole.ADMIN]:            raise HTTPException(status_code=403, detail="Permission denied")
            
        stmt = select(User)
        if q:
            q = q.strip()
            if q.isdigit():
                stmt = stmt.where(User.telegram_id == int(q))
            elif q.startswith('@'):
                stmt = stmt.where(User.username.ilike(f"%{q[1:]}%"))
            else:
                stmt = stmt.where(or_(
                    User.username.ilike(f"%{q}%"),
                    User.full_name.ilike(f"%{q}%"),
                    User.telegram_id.cast(String).ilike(f"%{q}%")
                ))

        stmt = stmt.order_by(User.created_at.desc())
        users = (await session.execute(stmt)).scalars().all()
        
        return templates.TemplateResponse("users_manage.html", {
            "request": request,
            "user": user,
            "all_users": users,
            "roles": [r.value for r in UserRole],
            "active_page": "users",
            "search_query": q or ""
        })

@router.post("/users/create")
async def create_new_user(
    telegram_id: int = Form(...),
    login: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    current_admin: User = Depends(get_current_user)
):
    """Создание нового сотрудника и WebAccount."""
    async with SessionFactory() as session:
        if current_admin.role != UserRole.OWNER:
            raise HTTPException(status_code=403, detail="Only OWNER can create users")
            
        # 1. Проверяем, существует ли пользователь в боте
        stmt = select(User).where(User.telegram_id == telegram_id)
        user = (await session.execute(stmt)).scalar_one_or_none()
        
        if not user:
            # Создаем нового пользователя бота
            user = User(
                telegram_id=telegram_id,
                full_name=f"New Worker ({login})",
                role=UserRole(role),
                is_active=True
            )
            session.add(user)
            await session.flush() # Получаем ID
        else:
            # Если пользователь есть, просто обновляем его роль
            user.role = UserRole(role)

        # 2. Проверяем WebAccount
        from src.database.models.web_control import WebAccount
        stmt_web = select(WebAccount).where(WebAccount.login == login)
        existing_web = (await session.execute(stmt_web)).scalar_one_or_none()
        if existing_web:
            raise HTTPException(status_code=400, detail="Логин уже занят")

        # 3. Создаем WebAccount
        new_web = WebAccount(
            user_id=user.id,
            login=login,
            password_hash=AuthService.hash_password(password),
            is_active=True
        )
        session.add(new_web)
        
        await session.commit()
        await log_admin_action(admin_id=current_admin.id, action="CREATE_USER", target_type="user", target_id=user.id, details=f"Создан аккаунт {login} с ролью {role}")
        
        return RedirectResponse(url="/nexus/users", status_code=303)

@router.post("/users/{target_id}/role")
async def update_user_role(target_id: int, new_role: str = Form(...), user: User = Depends(get_current_user)):
    """Изменение роли пользователя."""
    async with SessionFactory() as session:
        if user.role not in [UserRole.OWNER, UserRole.ADMIN]:
            raise HTTPException(status_code=403, detail="Permission denied")
            
        target = await session.get(User, target_id)
        if target:
            # Нельзя менять роль самому себе через этот интерфейс (безопасность)
            if target.id == user.id:
                raise HTTPException(status_code=400, detail="Cannot change your own role")
                
            old_role = target.role
            target.role = UserRole(new_role)
            await session.commit()
            
            # Пишем лог
            await log_admin_action(
                admin_id=user.id,
                action="UPDATE_ROLE",
                target_type="user",
                target_id=target.id,
                details=f"Роль изменена: {old_role} -> {new_role}"
            )
            return RedirectResponse(url="/nexus/users", status_code=303)
        return HTTPException(status_code=404)

@router.get("/audit", response_class=HTMLResponse)
async def get_audit_log(request: Request, user: User = Depends(get_current_user)):
    """Страница журнала аудита (только для OWNER)."""

    async with SessionFactory() as session:
        if user.role != UserRole.OWNER:            raise HTTPException(status_code=403, detail="Permission denied")
            
        stmt = (
            select(AdminAuditLog)
            .options(joinedload(AdminAuditLog.admin))
            .order_by(AdminAuditLog.created_at.desc())
            .limit(100)
        )
        logs = (await session.execute(stmt)).scalars().all()
        
        return templates.TemplateResponse("audit_log.html", {
            "request": request,
            "user": user,
            "logs": logs,
            "active_page": "audit"
        })

@router.get("/moderation", response_class=HTMLResponse)
async def get_moderation_panel(request: Request, user: User = Depends(get_current_user)):
    """Панель модерации активных симок (для OWNER и ADMIN)."""

    async with SessionFactory() as session:
        if user.role not in [UserRole.OWNER, UserRole.ADMIN]:            raise HTTPException(status_code=403, detail="Permission denied")
            
        # Загружаем симки в работе
        stmt = (
            select(Submission)
            .options(joinedload(Submission.category), joinedload(Submission.seller), joinedload(Submission.buyer))
            .where(Submission.status.in_([SubmissionStatus.IN_WORK, SubmissionStatus.WAIT_CONFIRM]))
            .order_by(Submission.assigned_at.desc())
        )
        active_items = (await session.execute(stmt)).scalars().all()
        
        # Словарь цветов для категорий (Улучшение 3)
        cat_colors = {
            "beeline": "from-yellow-400 to-amber-600",
            "mts": "from-red-500 to-rose-700",
            "megafon": "from-emerald-400 to-green-600",
            "tele2": "from-slate-400 to-slate-600",
            "tinkoff": "from-yellow-300 to-yellow-500",
        }

        return templates.TemplateResponse("moderation.html", {
            "request": request,
            "user": user,
            "items": active_items,
            "cat_colors": cat_colors,
            "active_page": "moderation"
        })

@router.get("/search")
async def search_submissions(q: str, user: User = Depends(get_current_user)):
    """API для глобального поиска по номеру телефона или ID."""
    async with SessionFactory() as session:
        is_admin = user.role in [UserRole.OWNER, UserRole.ADMIN]
        
        # 1. Формируем условия поиска
        conditions = []
        
        # Если в поиске только цифры
        if q.isdigit():
            # Если это похоже на ID (короткое число)
            if len(q) < 7:
                conditions.append(Submission.id == int(q))
            
            # Поиск по номеру (полный или последние цифры)
            if len(q) >= 3:
                conditions.append(Submission.phone_normalized.like(f"%{q}"))
        else:
            # Поиск по вхождению текста (если есть)
            conditions.append(Submission.phone_normalized.like(f"%{q}%"))

        if not conditions:
            return HTMLResponse(content='<div class="p-12 text-center text-white/10 uppercase tracking-widest text-xs italic">Введите минимум 3 цифры...</div>')

        stmt = (
            select(Submission)
            .options(joinedload(Submission.category))
            .where(or_(*conditions))
            .order_by(Submission.updated_at.desc())
            .limit(15)
        )
        
        # Ограничение доступа для байеров
        if user.role == UserRole.SIMBUYER:
            stmt = stmt.where(Submission.delivered_to_chat == user.telegram_id)
            
        results = (await session.execute(stmt)).scalars().all()
        
        html = ""
        for res in results:
            status_color = "text-nexus-cyan"
            if res.status == SubmissionStatus.ACCEPTED: status_color = "text-emerald-500"
            elif res.status == SubmissionStatus.BLOCKED: status_color = "text-red-500"
            elif res.status == SubmissionStatus.NOT_A_SCAN: status_color = "text-amber-500"

            # Кнопка "В Бот" только для админов
            bot_btn = ""
            if is_admin:
                bot_btn = f"""
                <button hx-post="/nexus/submission/{res.id}/show-in-bot" hx-swap="outerHTML"
                        class="p-2 bg-white/5 border border-white/10 rounded-lg text-white/40 hover:text-nexus-cyan transition-all" title="Показать в Telegram">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/></svg>
                </button>
                """

            html += f"""
            <div class="flex items-center justify-between p-4 hover:bg-white/5 border-b border-white/5 transition-all group">
                <a href="/nexus/submission/{res.id}" class="flex items-center gap-4 flex-1">
                    <div class="w-10 h-10 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center font-mono text-[10px] text-white/40 group-hover:border-nexus-cyan/30 transition-all">
                        #{res.id}
                    </div>
                    <div>
                        <div class="text-white font-bold group-hover:text-nexus-cyan transition-colors">{res.phone_normalized or 'Н/Д'}</div>
                        <div class="text-[10px] text-white/40 uppercase tracking-widest">{res.category.title}</div>
                    </div>
                </a>
                <div class="flex items-center gap-3">
                    <div class="{status_color} font-mono text-[10px] uppercase tracking-widest font-bold px-2 py-1 bg-white/5 rounded border border-white/5">{res.status}</div>
                    {bot_btn}
                </div>
            </div>
            """
        return HTMLResponse(content=html if html else '<div class="p-12 text-center text-white/10 uppercase tracking-widest text-xs italic">Ничего не найдено</div>')

@router.post("/esim/{sub_id}/action/{action}")
async def process_esim_action(sub_id: int, action: str, user: User = Depends(get_current_user), bot: Bot = Depends(get_bot)):
    """Обработка действий с eSIM (изменение статуса)."""
    async with SessionFactory() as session:
        sub = await session.get(Submission, sub_id)
        if not sub:
            return HTMLResponse(content='<div class="text-red-400">Not found</div>')

        old_status = sub.status
        is_simbuyer = user.role == UserRole.SIMBUYER

        # ЛОГИКА ЗАМОРОЗКИ И ПРАВ ДОСТУПА
        if is_simbuyer:
            # 1. Симбайер не может переопределить решение Админа/Овнера (если статус уже ACCEPTED)
            if old_status == SubmissionStatus.ACCEPTED:
                return HTMLResponse(content='<div class="text-red-400 p-2 bg-red-900/20 border border-red-900 rounded">❌ Статус заморожен администратором.</div>')
            
            # 2. Симбайер может ставить только BLOCKED или NOT_A_SCAN
            if action not in ["block", "not_scan"]:
                return HTMLResponse(content='<div class="text-red-400 p-2 bg-red-900/20 border border-red-900 rounded">❌ Недостаточно прав для этого действия.</div>')

        # ПРИМЕНЕНИЕ СТАТУСА
        notification_text = None
        if action == "block": 
            sub.status = SubmissionStatus.BLOCKED
            notification_text = f"⚠️ *ОПЕРАТИВНЫЙ КОНТРОЛЬ*\n\nВаша сим-карта `{sub.phone_normalized}` была *ЗАБЛОКИРОВАНА*.\nКатегория: {sub.category.title}\nID: #`{sub.id}`"
        elif action == "not_scan": 
            sub.status = SubmissionStatus.NOT_A_SCAN
        elif action == "accept" and not is_simbuyer: # Только Админ/Овнер
            sub.status = SubmissionStatus.ACCEPTED
            
        if old_status != sub.status:
            await session.commit()
            
            # УВЕДОМЛЕНИЕ СЕЛЛЕРУ (ТЗ: "уведомление поступет селлеру в личку")
            if notification_text and sub.seller_id:
                try:
                    await bot.send_message(sub.seller_id, notification_text, parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"Failed to notify seller {sub.seller_id}: {e}")

            # ВИЗУАЛЬНЫЙ ЛОГ В ТИКЕТАХ (Улучшение 2)
            from src.database.models.submission import SupportTicket, ChatMessage
            ticket_stmt = select(SupportTicket).where(SupportTicket.submission_id == sub.id)
            ticket = (await session.execute(ticket_stmt)).scalar_one_or_none()
            if ticket:
                sys_msg = ChatMessage(
                    ticket_id=ticket.id,
                    sender_id=None, # None означает системное сообщение
                    text=f"⚙️ СИСТЕМА: Статус изменен на {sub.status.upper()} пользователем {user.full_name}"
                )
                session.add(sys_msg)
                await session.commit()

            # Пишем аудит-лог
            await log_admin_action(
                admin_id=user.id,
                action=f"ACTION_{action.upper()}",
                target_type="submission",
                target_id=sub.id,
                details=f"Статус изменен: {old_status} -> {sub.status} пользователем {user.role}"
            )
            
            return HTMLResponse(content='<script>window.location.reload();</script>')
        
        return HTMLResponse(content='')
