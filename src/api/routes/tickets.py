from __future__ import annotations

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from src.database.session import SessionFactory
from src.database.models.user import User
from src.database.models.web_control import SupportTicket, ChatMessage
from src.api.deps import templates, get_current_user, RoleChecker

router = APIRouter(prefix="/nexus/tickets", tags=["Tickets"])

@router.get("", response_class=HTMLResponse)
async def get_tickets(request: Request, user: User = Depends(get_current_user)):
    async with SessionFactory() as session:
        # SIMBUYER видит только свои тикеты
        stmt = select(SupportTicket).order_by(SupportTicket.created_at.desc())
        if user.role == "simbuyer":
            stmt = stmt.where(SupportTicket.creator_id == user.id)
            
        result = await session.execute(stmt)
        tickets = result.scalars().all()
        return templates.TemplateResponse("tickets.html", {
            "request": request, 
            "user": user,
            "tickets": tickets, 
            "active_page": "tickets"
        })

@router.post("/create")
async def create_ticket(
    subject: str = Form(...),
    submission_id: int = Form(...),
    user: User = Depends(get_current_user)
):
    async with SessionFactory() as session:
        new_ticket = SupportTicket(
            creator_id=user.id,
            submission_id=submission_id,
            subject=subject,
            status="open"
        )
        session.add(new_ticket)
        await session.commit()
        return RedirectResponse(url=f"/nexus/tickets/{new_ticket.id}", status_code=303)

@router.get("/{ticket_id}", response_class=HTMLResponse)
async def view_ticket(ticket_id: int, request: Request, user: User = Depends(get_current_user)):
    """Страница переписки внутри конкретного тикета."""
    async with SessionFactory() as session:
        stmt = select(SupportTicket).options(
            joinedload(SupportTicket.messages).joinedload(ChatMessage.sender)
        ).where(SupportTicket.id == ticket_id)
        
        ticket = (await session.execute(stmt)).scalar_one_or_none()
        
        if not ticket:
            raise HTTPException(status_code=404, detail="Тикет не найден")

        # Проверка доступа
        if user.role == "simbuyer" and ticket.creator_id != user.id:
            raise HTTPException(status_code=403, detail="Доступ запрещен")

        messages = sorted(ticket.messages, key=lambda m: m.created_at)

        return templates.TemplateResponse("ticket_chat.html", {
            "request": request, 
            "user": user,
            "ticket": ticket,
            "messages": messages,
            "active_page": "tickets"
        })

@router.post("/{ticket_id}/message", response_class=HTMLResponse)
async def send_message(
    ticket_id: int,
    request: Request,
    text: str = Form(...),
    user: User = Depends(get_current_user)
):
    """HTMX-обработчик отправки нового сообщения."""
    async with SessionFactory() as session:
        # Проверка доступа к тикету
        ticket = await session.get(SupportTicket, ticket_id)
        if not ticket:
            raise HTTPException(status_code=404)
        if user.role == "simbuyer" and ticket.creator_id != user.id:
            raise HTTPException(status_code=403)

        new_msg = ChatMessage(
            ticket_id=ticket_id,
            sender_id=user.id,
            text=text
        )
        session.add(new_msg)
        await session.commit()
        await session.refresh(new_msg, ["sender"])

        return templates.TemplateResponse("components/chat_message.html", {
            "request": request,
            "msg": new_msg,
            "current_user_id": user.id
        })
