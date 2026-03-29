"""Персональные точки сброса счётчиков «Принято/Брак» для каждого админа.

Каждый админ может обнулить свои личные счётчики независимо.
Хранится {telegram_id: ISO datetime} в data/admin_personal_epoch.json.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_EPOCH_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "admin_personal_epoch.json"


def _load() -> dict[str, str]:
    try:
        return json.loads(_EPOCH_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(data: dict[str, str]) -> None:
    _EPOCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    _EPOCH_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_personal_epoch(telegram_id: int) -> datetime | None:
    """Возвращает личную точку обнуления для данного telegram_id или None."""
    data = _load()
    iso = data.get(str(telegram_id))
    if iso:
        try:
            return datetime.fromisoformat(iso)
        except ValueError:
            pass
    return None


def set_personal_epoch(telegram_id: int, dt: datetime | None = None) -> datetime:
    """Устанавливает личную точку обнуления. По умолчанию — текущий момент UTC."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    data = _load()
    data[str(telegram_id)] = dt.isoformat()
    _save(data)
    logger.info("Personal epoch set for telegram_id=%s → %s", telegram_id, dt.isoformat())
    return dt
