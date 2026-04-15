from __future__ import annotations

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from src.database.session import SessionFactory
from src.database.models.web_control import SupportTicket, ChatMessage
from src.api.routes.nexus import get_current_user

# Сначала объявляем роутер
router = APIRouter(prefix="/nexus/tickets", tags=["Tickets"])

@router.get("", response_class=HTMLResponse)
async def get_tickets(request: Request, user_data: dict = Depends(get_current_user)):
    from src.api.app import templates
    async with SessionFactory() as session:
        stmt = (
            select(SupportTicket)
            .options(joinedload(SupportTicket.creator))
            .order_by(SupportTicket.created_at.desc())
        )
        result = await session.execute(stmt)
        tickets = result.scalars().all()
        return templates.TemplateResponse("tickets.html", {
            "request": request, 
            "user": {"user_id": user_data.get("user_id"), "role": user_data.get("role")},
            "tickets": tickets, 
            "active_page": "tickets"
        })

@router.post("/create")
async def create_ticket(
    subject: str = Form(...),
    submission_id: int = Form(...),
    user_data: dict = Depends(get_current_user)
):
    async with SessionFactory() as session:
        new_ticket = SupportTicket(
            creator_id=user_data.get("user_id"),
            submission_id=submission_id,
            subject=subject,
            status="open"
        )
        session.add(new_ticket)
        await session.commit()
        return RedirectResponse(url=f"/nexus/tickets/{new_ticket.id}", status_code=303)

@router.get("/{ticket_id}", response_class=HTMLResponse)
async def view_ticket(ticket_id: int, request: Request, user_data: dict = Depends(get_current_user)):
    """Страница переписки внутри конкретного тикета."""
    from src.api.app import templates
    async with SessionFactory() as session:
        # Подгружаем тикет и связанные сообщения (отсортированные по времени)
        stmt = select(SupportTicket).options(
            joinedload(SupportTicket.creator),
            joinedload(SupportTicket.messages).joinedload(ChatMessage.sender)
        ).where(SupportTicket.id == ticket_id)
        
        ticket = (await session.execute(stmt)).scalar_one_or_none()
        
        if not ticket:
            raise HTTPException(status_code=404, detail="Тикет не найден")

        # Чтобы сообщения шли сверху вниз (старые -> новые)
        messages = sorted(ticket.messages, key=lambda m: m.created_at)

        return templates.TemplateResponse("ticket_chat.html", {
            "request": request, 
            "user": {"username": user_data.get("sub"), "user_id": user_data.get("user_id")},
            "ticket": ticket,
            "messages": messages,
            "active_page": "tickets"
        })

@router.post("/{ticket_id}/message", response_class=HTMLResponse)
async def send_message(
    ticket_id: int,
    request: Request,
    text: str = Form(...),
    user_data: dict = Depends(get_current_user)
):
    """HTMX-обработчик отправки нового сообщения."""
    from src.api.app import templates
    async with SessionFactory() as session:
        new_msg = ChatMessage(
            ticket_id=ticket_id,
            sender_id=user_data.get("user_id"),
            text=text
        )
        session.add(new_msg)
        await session.commit()
        await session.refresh(new_msg, ["sender"]) # Подгружаем отправителя

        # Возвращаем только HTML-кусочек нового сообщения для вставки в чат
        return templates.TemplateResponse("components/chat_message.html", {
            "request": request,
            "msg": new_msg,
            "current_user_id": user_data.get("user_id")
        })
