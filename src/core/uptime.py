"""Process uptime tracker.

Call ``mark_start()`` once at application boot (in run_application()).
``get_uptime_str()`` can then be called from any handler.
"""

from __future__ import annotations

from datetime import datetime, timezone

_start_time: datetime | None = None


def mark_start() -> None:
    """Record the moment the bot process became ready. Idempotent."""
    global _start_time
    if _start_time is None:
        _start_time = datetime.now(timezone.utc)


def get_uptime_str() -> str:
    """Return a human-readable uptime string like '2d 4h 13m 5s'."""
    if _start_time is None:
        return "N/A"
    delta = datetime.now(timezone.utc) - _start_time
    total_seconds = int(delta.total_seconds())
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)
