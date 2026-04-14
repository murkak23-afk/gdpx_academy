from __future__ import annotations

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from src.database.session import SessionFactory
from src.database.models.web_control import SupportTicket
from src.api.routes.nexus import get_current_user

router = APIRouter(prefix="/nexus/tickets", tags=["Tickets"])

@router.get("", response_class=HTMLResponse)
async def get_tickets(request: Request, user_data: dict = Depends(get_current_user)):
    from src.api.app import templates
    async with SessionFactory() as session:
        stmt = select(SupportTicket).order_by(SupportTicket.created_at.desc())
        result = await session.execute(stmt)
        tickets = result.scalars().all()
        return templates.TemplateResponse("tickets.html", {
            "request": request, 
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
