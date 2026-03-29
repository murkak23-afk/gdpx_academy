"""Управление точкой обнуления статистики (stats epoch).

Хранит UTC-метку, после которой считается статистика.
Записи до этой метки игнорируются — как если бы их не было.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_EPOCH_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "stats_epoch.json"


def get_stats_epoch() -> datetime | None:
    """Возвращает текущую метку обнуления или None (нет ограничений)."""
    try:
        raw = _EPOCH_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        iso = data.get("reset_at")
        if iso:
            return datetime.fromisoformat(iso)
    except (FileNotFoundError, json.JSONDecodeError, ValueError, KeyError):
        pass
    return None


def set_stats_epoch(dt: datetime | None = None) -> datetime:
    """Устанавливает метку обнуления. По умолчанию — текущий момент UTC."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    _EPOCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"reset_at": dt.isoformat(), "note": "Stats reset point"}
    _EPOCH_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Stats epoch set to %s", dt.isoformat())
    return dt
