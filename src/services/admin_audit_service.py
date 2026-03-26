from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.admin_audit import AdminAuditLog


class AdminAuditService:
    """Сервис записи аудита действий админа."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(
        self,
        admin_id: int,
        action: str,
        target_type: str | None = None,
        target_id: int | None = None,
        details: str | None = None,
    ) -> None:
        record = AdminAuditLog(
            admin_id=admin_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details,
        )
        self._session.add(record)
        await self._session.commit()
