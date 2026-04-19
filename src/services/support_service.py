from __future__ import annotations
import logging
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import select, desc, func
from sqlalchemy.orm import joinedload
from src.database.models.web_control import SupportTicket, ChatMessage
from src.database.models.user import User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

class SupportService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_ticket(self, user_id: int, subject: str, submission_id: Optional[int] = None) -> SupportTicket:
        ticket = SupportTicket(
            creator_id=user_id,
            subject=subject,
            submission_id=submission_id,
            status="open"
        )
        self._session.add(ticket)
        await self._session.flush()
        return ticket

    async def add_message(self, ticket_id: int, sender_id: int, text: str) -> ChatMessage:
        message = ChatMessage(
            ticket_id=ticket_id,
            sender_id=sender_id,
            text=text,
            is_read=False
        )
        self._session.add(message)
        
        # Если отправитель — админ/овнер, и в тикете еще нет ответственного, назначаем его
        ticket = await self.get_ticket_by_id(ticket_id)
        if ticket and not ticket.assigned_admin_id:
            from src.domain.users.user_service import UserService
            user_svc = UserService(self._session)
            sender = await user_svc.get_by_id(sender_id)
            if sender and sender.role in ["admin", "owner"]:
                ticket.assigned_admin_id = sender_id
        
        await self._session.flush()
        return message

    async def get_user_tickets(self, user_id: int, limit: int = 10) -> List[SupportTicket]:
        stmt = (
            select(SupportTicket)
            .where(SupportTicket.creator_id == user_id)
            .order_by(desc(SupportTicket.created_at))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_open_tickets(self, limit: int = 20) -> List[SupportTicket]:
        stmt = (
            select(SupportTicket)
            .options(joinedload(SupportTicket.creator))
            .where(SupportTicket.status == "open")
            .order_by(desc(SupportTicket.created_at))
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_tickets(self, limit: int = 50, offset: int = 0) -> tuple[List[SupportTicket], int]:
        """Для владельца: история всех тикетов."""
        count_stmt = select(func.count(SupportTicket.id))
        total = (await self._session.execute(count_stmt)).scalar() or 0

        stmt = (
            select(SupportTicket)
            .options(joinedload(SupportTicket.creator), joinedload(SupportTicket.assigned_admin))
            .order_by(desc(SupportTicket.created_at))
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total

    async def get_ticket_by_id(self, ticket_id: int) -> Optional[SupportTicket]:
        stmt = (
            select(SupportTicket)
            .options(joinedload(SupportTicket.creator))
            .where(SupportTicket.id == ticket_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_ticket_messages(self, ticket_id: int) -> List[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .options(joinedload(ChatMessage.sender))
            .where(ChatMessage.ticket_id == ticket_id)
            .order_by(ChatMessage.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def close_ticket(self, ticket_id: int) -> bool:
        ticket = await self.get_ticket_by_id(ticket_id)
        if ticket:
            ticket.status = "closed"
            await self._session.flush()
            return True
        return False
