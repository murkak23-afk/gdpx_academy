import logging
from typing import Any
from src.database.models.admin_audit import AdminAuditLog
from src.database.session import SessionFactory

logger = logging.getLogger(__name__)

async def log_admin_action(
    admin_id: int, 
    action: str, 
    target_type: str = None, 
    target_id: int = None, 
    details: str = None
):
    """
    Записывает действие администратора в базу данных.
    """
    async with SessionFactory() as session:
        try:
            new_log = AdminAuditLog(
                admin_id=admin_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                details=details
            )
            session.add(new_log)
            await session.commit()
        except Exception as e:
            logger.error(f"❌ Ошибка при записи в Audit Log: {e}")
