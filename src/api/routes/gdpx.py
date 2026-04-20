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
from src.services.auth_service import AuthService
from src.domain.submission.submission_service import SubmissionService

router = APIRouter(prefix="/gdpx", tags=["GDPX"])
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

        # 24h Activity Data (Improvement #2)
        activity_stmt = (
            select(func.extract('hour', Submission.created_at).label('hour'), func.count(Submission.id))
            .where(Submission.created_at >= (datetime.now(timezone.utc) - timedelta(hours=24)))
            .group_by(func.extract('hour', Submission.created_at))
            .order_by('hour')
        )
        activity_raw = (await session.execute(activity_stmt)).all()
        activity_data = [0] * 24
        for hr, count in activity_raw:
            activity_data[int(hr)] = count

        return templates.TemplateResponse("dashboard.html", {
            "request": request, 
            "user": user,
            "stats": stats,
            "activity_data": activity_data,
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

@router.post("/owner/archive/clear")
async def clear_reports_buffer(user: User = Depends(get_current_user)):
    """Очистка буфера отработанного товара (архивация)."""
    async with SessionFactory() as session:
        if user.role != UserRole.OWNER:
            raise HTTPException(status_code=403)
            
        # Архивируем все отработанные заявки
        from sqlalchemy import update
        from src.database.models.enums import SubmissionStatus
        from datetime import datetime, timezone
        
        stmt = update(Submission).where(
            and_(
                Submission.status.in_([
                    SubmissionStatus.ACCEPTED, 
                    SubmissionStatus.REJECTED, 
                    SubmissionStatus.BLOCKED,
                    SubmissionStatus.NOT_A_SCAN
                ]),
                Submission.is_archived == False
            )
        ).values(
            is_archived=True,
            archived_at=datetime.now(timezone.utc)
        )
        
        await session.execute(stmt)
        await session.commit()
        
        await log_admin_action(admin_id=user.id, action="CLEAR_REPORTS_BUFFER", details="Буфер отработанного товара очищен")
        
        return HTMLResponse(content='<script>window.location.reload();</script>')
@router.post("/archive/batch-export")
async def export_batch_csv(ids: str = Form(...), user: User = Depends(admin_only)):
    """Выгрузка выбранных отчетов в CSV."""
    async with SessionFactory() as session:
        try:
            target_ids = [int(i) for i in ids.split(",") if i.strip()]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid IDs")
            
        stmt = select(Submission).options(joinedload(Submission.category)).where(Submission.id.in_(target_ids)).order_by(Submission.updated_at.desc())
        items = (await session.execute(stmt)).scalars().all()
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Phone", "Category", "Status", "Price", "Date"])
        
        for i in items:
            writer.writerow([i.id, i.phone_normalized or "N/A", i.category.title, i.status, i.purchase_price or 0, i.updated_at.strftime("%Y-%m-%d %H:%M")])
            
        response = StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv"
        )
        response.headers["Content-Disposition"] = "attachment; filename=gdpx_batch_export.csv"
        return response


@router.get("/archive", response_class=HTMLResponse)
async def get_archive(request: Request, date: str = None, user: User = Depends(get_current_user)):
    """Архив отгрузок за прошлые дни."""
    async with SessionFactory() as session:
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Базовый запрос: только отработанные
        base_stmt = select(Submission).where(Submission.status != SubmissionStatus.PENDING)
        
        if date:
            try:
                selected_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                next_day = selected_date + timedelta(days=1)
                base_stmt = base_stmt.where(Submission.updated_at >= selected_date, Submission.updated_at < next_day)
                is_archive_view = True
            except ValueError:
                # Если дата кривая, показываем за все время до сегодня
                base_stmt = base_stmt.where(Submission.updated_at < today_start)
                is_archive_view = True
        else:
            # По умолчанию в Архиве показываем все до сегодня
            base_stmt = base_stmt.where(Submission.updated_at < today_start)
            is_archive_view = True

        if user.role == UserRole.SIMBUYER:
            base_stmt = base_stmt.where(Submission.buyer_id == user.id)
            
        shipments_stmt = base_stmt.options(
            joinedload(Submission.category), 
            joinedload(Submission.buyer)
        ).order_by(Submission.updated_at.desc()).limit(1000)
        
        shipments = (await session.execute(shipments_stmt)).scalars().all()
        
        # KPI считаем по выборке
        total_taken = len(shipments)
        accepted_list = [s for s in shipments if s.status == SubmissionStatus.ACCEPTED]
        
        stats = {
            "total_taken": total_taken,
            "accepted": len(accepted_list),
            "blocks": len([s for s in shipments if s.status == SubmissionStatus.BLOCKED]),
            "not_scans": len([s for s in shipments if s.status == SubmissionStatus.NOT_A_SCAN]),
            "total_spend": sum([s.purchase_price or 0 for s in accepted_list])
        }
        stats["success_rate"] = round((stats["accepted"] / total_taken * 100), 1) if total_taken > 0 else 0

        return templates.TemplateResponse("archive.html", {
            "request": request,
            "user": user,
            "shipments": shipments,
            "stats": stats,
            "selected_date": date,
            "active_page": "archive",
            "show_batch_actions": user.role in [UserRole.OWNER, UserRole.ADMIN],
        })

@router.get("/stats", response_class=HTMLResponse)
async def get_current_stats(request: Request, user: User = Depends(get_current_user)):
    """Оперативная статистика за текущий день."""
    async with SessionFactory() as session:
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        base_stmt = select(Submission).where(Submission.updated_at >= today_start)
        
        if user.role == UserRole.SIMBUYER:
            base_stmt = base_stmt.where(Submission.buyer_id == user.id)
            
        shipments_stmt = base_stmt.options(
            joinedload(Submission.category), 
            joinedload(Submission.buyer)
        ).order_by(Submission.updated_at.desc())
        
        shipments = (await session.execute(shipments_stmt)).scalars().all()
        
        total_taken = len([s for s in shipments if s.status != SubmissionStatus.PENDING])
        accepted_list = [s for s in shipments if s.status == SubmissionStatus.ACCEPTED]
        
        stats = {
            "total_taken": total_taken,
            "accepted": len(accepted_list),
            "blocks": len([s for s in shipments if s.status == SubmissionStatus.BLOCKED]),
            "not_scans": len([s for s in shipments if s.status == SubmissionStatus.NOT_A_SCAN]),
            "total_spend": sum([s.purchase_price or 0 for s in accepted_list])
        }
        stats["success_rate"] = round((stats["accepted"] / total_taken * 100), 1) if total_taken > 0 else 0

        return templates.TemplateResponse("archive.html", { # Используем тот же шаблон, но с другими данными
            "request": request,
            "user": user,
            "shipments": shipments,
            "stats": stats,
            "is_today": True,
            "active_page": "stats",
            "show_batch_actions": user.role in [UserRole.OWNER, UserRole.ADMIN],
        })

@router.get("/submission/{sub_id}", response_class=HTMLResponse)
async def view_submission(sub_id: int, request: Request, user: User = Depends(get_current_user)):
    """Детальная страница одной eSIM (скана)."""
    async with SessionFactory() as session:
        # Базовая выборка с категорией
        stmt = select(Submission).options(
            joinedload(Submission.category),
            joinedload(Submission.buyer),
            joinedload(Submission.admin)
        ).where(Submission.id == sub_id)
        
        # Загружаем продавца только для админов и овнера (Изоляция данных)
        if user.role in [UserRole.OWNER, UserRole.ADMIN]:
            stmt = stmt.options(joinedload(Submission.seller))
            
        res = await session.execute(stmt)
        sub = res.scalar_one_or_none()
        
        if not sub:
            raise HTTPException(status_code=404, detail="eSIM не найдена")

        if user.role == UserRole.SIMBUYER and sub.buyer_id != user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен")

        return templates.TemplateResponse("submission_detail.html", {
            "request": request,
            "user": user,
            "sub": sub,
            "active_page": "archive",
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
            status_color = "text-gdpx-cyan border-gdpx-cyan/30 bg-gdpx-cyan/10 shadow-[0_0_10px_rgba(0,217,255,0.1)]" if cat.is_active else "text-white/20 border-white/5 bg-white/5"
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
            return RedirectResponse(url="/gdpx/categories", status_code=303)
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
        return RedirectResponse(url="/gdpx/categories", status_code=303)

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
            return RedirectResponse(url="/gdpx/categories", status_code=303)
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
        
        return RedirectResponse(url=f"/gdpx/users/{target_id}/delivery", status_code=303)

@router.post("/users/delivery/{cfg_id}/delete")
async def delete_delivery_config(cfg_id: int, user: User = Depends(admin_only)):
    """Удаление маршрута выдачи."""
    async with SessionFactory() as session:
        cfg = await session.get(DeliveryConfig, cfg_id)
        if cfg:
            target_id = cfg.user_id
            await session.delete(cfg)
            await session.commit()
            return RedirectResponse(url=f"/gdpx/users/{target_id}/delivery", status_code=303)
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
        return RedirectResponse(url=f"/gdpx/users/{target_id}/prices", status_code=303)

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
            return RedirectResponse(url=f"/gdpx/users/{target_id}/prices", status_code=303)
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
    category_id: int = Form(...),
    count: int = Form(1),
    user: User = Depends(get_current_user),
    bot: Bot = Depends(get_bot)
):
    """Выдача eSIM из инвентаря для симбайера с атомарным резервированием."""
    async with SessionFactory() as session:
        # 1. Ищем конфигурацию доставки
        from src.database.models.web_control import DeliveryConfig
        stmt_cfg = select(DeliveryConfig).where(
            DeliveryConfig.category_id == category_id,
            DeliveryConfig.user_id == user.id
        )
        cfg = (await session.execute(stmt_cfg)).scalar_one_or_none()

        if not cfg:
            return HTMLResponse(content='<div class="text-red-400 p-4 bg-red-900/20 border border-red-900 rounded-lg text-sm">Нет настроенного маршрута.</div>')

        # 2. АТОМАРНОЕ РЕЗЕРВИРОВАНИЕ (SELECT ... FOR UPDATE SKIP LOCKED)
        # Это предотвращает выдачу одних и тех же симок разным байерам
        stmt_reserve = (
            select(Submission)
            .where(Submission.category_id == category_id, Submission.status == SubmissionStatus.PENDING)
            .limit(count)
            .with_for_update(skip_locked=True)
        )
        items = list((await session.execute(stmt_reserve)).scalars().all())
        
        if len(items) < count:
            await session.rollback()
            return HTMLResponse(content=f'<div class="text-amber-400 p-4 bg-amber-900/20 border border-amber-900 rounded-lg text-sm">Недостаточно на складе. Доступно: {len(items)}</div>')

        item_ids = [item.id for item in items]
        
        # 3. Сразу помечаем их как занятые
        now = datetime.now(timezone.utc)
        for item in items:
            item.status = SubmissionStatus.IN_WORK
            item.buyer_id = user.id
            item.assigned_at = now
            item.delivered_to_chat = cfg.chat_id
            item.delivered_to_thread = cfg.thread_id
            
        await session.commit()

        # 4. Запускаем фоновую отгрузку в Telegram через ARQ (Reliable delivery)
        from src.core.cache import get_arq_pool
        arq_pool = await get_arq_pool()
        if arq_pool:
            await arq_pool.enqueue_job(
                'process_delivery_task',
                category_id=category_id,
                buyer_id=user.id,
                chat_id=cfg.chat_id,
                thread_id=cfg.thread_id,
                item_ids=item_ids
            )
        else:
            logger.error("ARQ Pool not available in take_esim_from_inventory")
        
        # Логируем
        await log_admin_action(
            admin_id=user.id,
            action="TAKE_ESIM_WEB",
            target_type="category",
            target_id=category_id,
            details=f"Выдано {len(item_ids)} шт. -> Чат {cfg.chat_id}"
        )
        
        return HTMLResponse(content='<script>window.location.href="/gdpx/my-esim"</script>')

@router.post("/submission/{sub_id}/show-in-bot")
async def show_in_bot(sub_id: int, request: Request, user: User = Depends(get_current_user), bot: Bot = Depends(get_bot)):
    """Отправка карточки сим-карты в личку (ТОЛЬКО ДЛЯ АДМИНОВ)."""
    async with SessionFactory() as session:
        if user.role == UserRole.SIMBUYER:
            raise HTTPException(status_code=403, detail="Simbuyers cannot use this")
            
        stmt = select(Submission).options(
            joinedload(Submission.category), 
            joinedload(Submission.seller)
        ).where(Submission.id == sub_id)
        sub = (await session.execute(stmt)).scalar_one_or_none()
        
        if not sub:
            return HTMLResponse(content="Not Found")

        # ПОЛНАЯ КАРТОЧКА ДЛЯ АДМИНА
        text = (
            f"🏮 *GDPX PROTOCOL: КАРТОЧКА #{sub.id}*\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"📱 *НОМЕР:* `{sub.phone_normalized or 'Н/Д'}`\n"
            f"🏷 *КАТЕГОРИЯ:* `{sub.category.title}`\n"
            f"⚙️ *СТАТУС:* `{sub.status.upper()}`\n\n"
            f"👤 *ПРОДАВЕЦ:* @{sub.seller.username or 'unknown'} (`{sub.seller.telegram_id}`)\n"
            f"📅 *СОЗДАНА:* _{sub.created_at.strftime('%d.%m.%Y %H:%M')}_\n\n"
            f"🔗 [Открыть в панели](https://{request.base_url.hostname}/gdpx/submission/{sub.id})"
        )
        
        try:
            if sub.telegram_file_id:
                await bot.send_photo(user.telegram_id, sub.telegram_file_id, caption=text, parse_mode="Markdown")
            else:
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

        return RedirectResponse(url=f"/gdpx/tickets/{ticket.id}", status_code=303)

@router.get("/owner/buyers", response_class=HTMLResponse)
async def get_owner_buyers(request: Request, q: Optional[str] = None, user: User = Depends(get_current_user)):
    """Страница управления покупателями (OWNER only)."""
    async with SessionFactory() as session:
        if user.role != UserRole.OWNER:
            raise HTTPException(status_code=403, detail="Permission denied")

        # Показываем только тех, кто является SIMBUYER
        stmt = select(User).where(User.role == UserRole.SIMBUYER)

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
            "active_page": "owner_buyers",
            "search_query": q or ""
        })

@router.get("/owner/sellers", response_class=HTMLResponse)
async def get_owner_sellers(request: Request, q: Optional[str] = None, user: User = Depends(get_current_user)):
    """Страница управления продавцами (OWNER only)."""
    async with SessionFactory() as session:
        if user.role != UserRole.OWNER:
            raise HTTPException(status_code=403, detail="Permission denied")

        stmt = select(User).where(User.role == UserRole.SELLER)

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
        sellers = (await session.execute(stmt)).scalars().all()

        return templates.TemplateResponse("owner_sellers.html", {
            "request": request,
            "user": user,
            "sellers": sellers,
            "active_page": "owner_sellers",
            "search_query": q or ""
        })

@router.get("/owner/sellers/{seller_id}", response_class=HTMLResponse)
async def get_seller_card(seller_id: int, request: Request, user: User = Depends(get_current_user)):
    """Детальная карточка продавца с аналитикой."""
    async with SessionFactory() as session:
        if user.role != UserRole.OWNER: raise HTTPException(status_code=403)

        seller = await session.get(User, seller_id)
        if not seller: raise HTTPException(status_code=404)

        # Статистика одобрений
        total_stmt = select(func.count(Submission.id)).where(Submission.user_id == seller_id)
        total_count = await session.scalar(total_stmt) or 0

        accepted_stmt = select(func.count(Submission.id)).where(
            Submission.user_id == seller_id, 
            Submission.status == SubmissionStatus.ACCEPTED
        )
        accepted_count = await session.scalar(accepted_stmt) or 0

        trust_score = round((accepted_count / total_count * 100), 1) if total_count > 0 else 0
            
        # История последних 20 симок
        history_stmt = (
            select(Submission)
            .options(joinedload(Submission.category))
            .where(Submission.user_id == seller_id)
            .order_by(Submission.created_at.desc())
            .limit(20)
        )
        history = (await session.execute(history_stmt)).scalars().all()

        return templates.TemplateResponse("seller_card.html", {
            "request": request,
            "user": user,
            "seller": seller,
            "stats": {
                "total": total_count,
                "accepted": accepted_count,
                "trust_score": trust_score
            },
            "history": history,
            "active_page": "owner_sellers"
        })
@router.get("/owner/admins", response_class=HTMLResponse)
async def get_owner_admins(request: Request, user: User = Depends(get_current_user)):
    """Страница управления админами (OWNER only) с KPI."""
    async with SessionFactory() as session:
        if user.role != UserRole.OWNER: raise HTTPException(status_code=403)
        
        # Загружаем всех админов
        stmt = select(User).where(User.role == UserRole.ADMIN)
        admins = (await session.execute(stmt)).scalars().all()
        
        # Собираем KPI (кол-во действий)
        admin_stats = {}
        for a in admins:
            count_stmt = select(func.count(AdminAuditLog.id)).where(AdminAuditLog.admin_id == a.id)
            admin_stats[a.id] = await session.scalar(count_stmt) or 0
            
        return templates.TemplateResponse("owner_admins.html", {
            "request": request, 
            "user": user, 
            "admins": admins, 
            "admin_stats": admin_stats,
            "active_page": "owner_admins"
        })

@router.get("/owner/audit-feed", response_class=HTMLResponse)
async def get_owner_audit_feed(request: Request, user: User = Depends(get_current_user)):
    """Живая лента действий админов (Двойной аудит)."""
    async with SessionFactory() as session:
        if user.role != UserRole.OWNER: raise HTTPException(status_code=403)
        
        # Последние 50 действий админов (исключая самого овнера)
        stmt = (
            select(AdminAuditLog)
            .options(joinedload(AdminAuditLog.admin))
            .where(AdminAuditLog.action.in_(["ACCEPT_SUB", "REJECT_SUB", "BLOCK_SUB"]))
            .order_by(AdminAuditLog.created_at.desc())
            .limit(50)
        )
        feed = (await session.execute(stmt)).scalars().all()
        
        return templates.TemplateResponse("audit_feed.html", {
            "request": request,
            "user": user,
            "feed": feed,
            "active_page": "audit"
        })

@router.post("/owner/audit/{log_id}/override")
async def override_admin_decision(
    log_id: int, 
    new_status: str = Form(...), 
    user: User = Depends(get_current_user),
    bot: Bot = Depends(get_bot)
):
    """Пересмотр решения админа (Двойной аудит)."""
    async with SessionFactory() as session:
        if user.role != UserRole.OWNER: raise HTTPException(status_code=403)
        
        log_entry = await session.get(AdminAuditLog, log_id)
        if not log_entry or log_entry.target_type != "submission":
            raise HTTPException(status_code=404)
            
        sub = await session.get(Submission, log_entry.target_id)
        if sub:
            old_status = sub.status
            sub.status = SubmissionStatus(new_status)
            await session.commit()
            
            # Логируем действие овнера
            await log_admin_action(
                admin_id=user.id,
                action="OVERRIDE_DECISION",
                target_type="submission",
                target_id=sub.id,
                details=f"Овнер пересмотрел решение админа {log_entry.admin_id}: {old_status} -> {new_status}"
            )
            
            # Уведомляем админа об ошибке (Обучение)
            try:
                msg = f"⚠️ *ВНИМАНИЕ (Двойной аудит)*\n\nОвнер пересмотрел ваше решение по заявке #{sub.id}.\nВаше решение: `{old_status}`\nНовое решение: `{new_status}`\n\nПожалуйста, учитывайте это в будущей работе."
                await bot.send_message(log_entry.admin_id, msg, parse_mode="Markdown")
            except: pass
            
        return RedirectResponse(url="/gdpx/owner/audit-feed", status_code=303)

@router.get("/users/{target_id}/cabinet", response_class=HTMLResponse)
async def get_simbuyer_cabinet(target_id: int, request: Request, user: User = Depends(get_current_user)):
    """Личный кабинет управления СИМбайером (настройка цен и доступов)."""
    async with SessionFactory() as session:
        if user.role != UserRole.OWNER:
            raise HTTPException(status_code=403, detail="Permission denied")
        
        target = await session.get(User, target_id)
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
            
        web_acc_stmt = select(WebAccount).where(WebAccount.user_id == target.id)
        web_acc = (await session.execute(web_acc_stmt)).scalar_one_or_none()
        
        categories_stmt = select(Category).order_by(Category.title)
        categories = (await session.execute(categories_stmt)).scalars().all()
        
        prices_stmt = select(SimbuyerPrice).where(SimbuyerPrice.user_id == target.id)
        prices_list = (await session.execute(prices_stmt)).scalars().all()
        prices_map = {p.category_id: p.price for p in prices_list}

        # Депозитный контроль (Улучшение #3): Объем за сутки
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        payout_stmt = select(func.sum(Submission.purchase_price)).where(
            Submission.delivered_to_chat == target.telegram_id,
            Submission.status == SubmissionStatus.ACCEPTED,
            Submission.updated_at >= today_start
        )
        daily_volume = await session.scalar(payout_stmt) or Decimal("0.00")
        
        return templates.TemplateResponse("simbuyer_cabinet.html", {
            "request": request,
            "user": user,
            "target": target,
            "web_acc": web_acc,
            "categories": categories,
            "prices_map": prices_map,
            "daily_volume": daily_volume,
            "active_page": "owner_buyers"
        })

@router.post("/users/{target_id}/cabinet/config")
async def update_simbuyer_config(
    target_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    bot: Bot = Depends(get_bot)
):
    """Обновление ценовой политики и доступов СИМбайера."""
    async with SessionFactory() as session:
        if user.role != UserRole.OWNER:
            raise HTTPException(status_code=403, detail="Permission denied")
            
        target = await session.get(User, target_id)
        form_data = await request.form()
        
        # 1. Обновление цен по категориям
        from sqlalchemy import delete
        await session.execute(delete(SimbuyerPrice).where(SimbuyerPrice.user_id == target_id))
        
        for key, value in form_data.items():
            if key.startswith("price_") and value:
                cat_id = int(key.replace("price_", ""))
                new_price = SimbuyerPrice(
                    user_id=target_id,
                    category_id=cat_id,
                    price=Decimal(value)
                )
                session.add(new_price)
        
        # 2. Обновление учетных данных
        login = form_data.get("login")
        password = form_data.get("password")
        
        if login or password:
            web_acc_stmt = select(WebAccount).where(WebAccount.user_id == target_id)
            web_acc = (await session.execute(web_acc_stmt)).scalar_one_or_none()
            
            if not web_acc:
                web_acc = WebAccount(user_id=target_id, login=login or f"user_{target_id}")
                session.add(web_acc)
            
            if login: web_acc.login = login
            if password: web_acc.password_hash = AuthService.hash_password(password)
            
        await session.commit()
        await log_admin_action(admin_id=user.id, action="UPDATE_SIMBUYER_CABINET", target_type="user", target_id=target_id, details="Обновлена ценовая политика и доступы")
        
        # УВЕДОМЛЕНИЕ ПОКУПАТЕЛЮ (Улучшение #3)
        try:
            notification = "🔔 *GDPX: Обновление конфигурации*\n\nВладелец обновил вашу ценовую политику или учетные данные. Пожалуйста, проверьте изменения в личном кабинете."
            await bot.send_message(target.telegram_id, notification, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to notify simbuyer {target_id}: {e}")
            
        return RedirectResponse(url=f"/gdpx/users/{target_id}/cabinet", status_code=303)

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
        
        # Сразу перекидываем в кабинет для настройки цен и параметров
        return RedirectResponse(url=f"/gdpx/users/{user.id}/cabinet", status_code=303)

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
            return RedirectResponse(url="/gdpx/users", status_code=303)
        return HTTPException(status_code=404)

@router.post("/users/{target_id}/delete")
async def delete_user(target_id: int, user: User = Depends(get_current_user)):
    """Полное удаление покупателя и его веб-доступа."""
    async with SessionFactory() as session:
        if user.role != UserRole.OWNER:
            raise HTTPException(status_code=403, detail="Only OWNER can delete users")
        
        target = await session.get(User, target_id)
        if target:
            # Удаляем цены, веб-аккаунт и самого юзера (каскад сработает для цен/логов если настроено, но лучше вручную)
            from sqlalchemy import delete
            await session.execute(delete(SimbuyerPrice).where(SimbuyerPrice.user_id == target_id))
            await session.execute(delete(WebAccount).where(WebAccount.user_id == target_id))
            await session.delete(target)
            
            await session.commit()
            await log_admin_action(admin_id=user.id, action="DELETE_USER", target_type="user", target_id=target_id, details="Полное удаление аккаунта и веб-доступа")
            
        return RedirectResponse(url="/gdpx/owner/buyers", status_code=303)

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
            status_color = "text-gdpx-cyan"
            if res.status == SubmissionStatus.ACCEPTED: status_color = "text-emerald-500"
            elif res.status == SubmissionStatus.BLOCKED: status_color = "text-red-500"
            elif res.status == SubmissionStatus.NOT_A_SCAN: status_color = "text-amber-500"

            # Кнопка "В Бот" только для админов
            bot_btn = ""
            if is_admin:
                bot_btn = f"""
                <button hx-post="/gdpx/submission/{res.id}/show-in-bot" hx-swap="outerHTML"
                        class="p-2 bg-white/5 border border-white/10 rounded-lg text-white/40 hover:text-gdpx-cyan transition-all" title="Показать в Telegram">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/></svg>
                </button>
                """

            html += f"""
            <div class="flex items-center justify-between p-4 hover:bg-white/5 border-b border-white/5 transition-all group">
                <a href="/gdpx/submission/{res.id}" class="flex items-center gap-4 flex-1">
                    <div class="w-10 h-10 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center font-mono text-[10px] text-white/40 group-hover:border-gdpx-cyan/30 transition-all">
                        #{res.id}
                    </div>
                    <div>
                        <div class="text-white font-bold group-hover:text-gdpx-cyan transition-colors">{res.phone_normalized or 'Н/Д'}</div>
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
            if notification_text and sub.user_id:
                try:
                    # Находим telegram_id селлера
                    stmt_seller = select(User.telegram_id).where(User.id == sub.user_id)
                    seller_tg_id = (await session.execute(stmt_seller)).scalar()
                    if seller_tg_id:
                        await bot.send_message(seller_tg_id, notification_text, parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"Failed to notify seller for sub {sub.id}: {e}")

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
