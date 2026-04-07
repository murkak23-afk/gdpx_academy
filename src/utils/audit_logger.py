"""Shadow logging для действий администраторов.

Все критические операции (выплаты, бан, рассылка) пишутся в logs/admin_actions.log
с ротацией (10 МБ × 5 резервных копий) через loguru file sink.

Использование в хендлерах:
    from src.utils.audit_logger import log_admin_action
    log_admin_action(admin_id=callback.from_user.id, action="payout_confirmed", amount="15.0 USDT", user_id=seller_id)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

_LOG_DIR = Path(__file__).parent.parent.parent / "logs"
_LOG_FILE = _LOG_DIR / "admin_actions.log"

_audit_sink_id: int | None = None
# Pre-bound logger for hot-path calls — avoids re-binding on every log_admin_action().
_audit_log = logger.bind(audit=True)


def setup_admin_audit_logger() -> None:
    """Инициализирует файловый loguru sink для audit-записей.

    Безопасен для повторного вызова (идемпотентен).
    Вызывать один раз при старте приложения (из main()).
    """
    global _audit_sink_id
    if _audit_sink_id is not None:
        return

    # Создаём директорию если она вдруг была удалена после деплоя.
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    _audit_sink_id = logger.add(
        str(_LOG_FILE),
        level="INFO",
        # Only write records that were explicitly bound with audit=True.
        filter=lambda record: record["extra"].get("audit") is True,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
        enqueue=True,   # thread-safe / async-safe writes
        colorize=False,
    )
    _audit_log.info("[ AUDIT LOGGER // ONLINE ] log_file={}", _LOG_FILE)


def log_admin_action(
    admin_id: int,
    action: str,
    **details: Any,
) -> None:
    """Записывает действие администратора в logs/admin_actions.log.

    Args:
        admin_id: telegram_id администратора.
        action:   краткий идентификатор действия (snake_case), напр. 'payout_confirmed'.
        **details: произвольные поля контекста (user_id, amount, category, etc.).

    Пример:
        log_admin_action(admin_id=123, action="user_banned", target_user_id=456, reason="spam")
    """
    if details:
        extra_str = " | ".join(f"{k}={v}" for k, v in details.items())
        _audit_log.info("admin_id={} action={} | {}", admin_id, action, extra_str)
    else:
        _audit_log.info("admin_id={} action={}", admin_id, action)
