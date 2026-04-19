"""Loguru-based logging setup for the entire application.

Usage
-----
Call ``setup_logging()`` once at process startup (before other imports that
log), then use loguru's ``logger`` directly in every module::

    from loguru import logger
    logger.info("hello {name}", name="world")

stdlib logging (aiogram, SQLAlchemy, uvicorn, aiohttp, …) is automatically
forwarded to loguru via ``InterceptHandler`` installed on the stdlib root
logger, so third-party libraries produce coloured, structured output too.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from loguru import Record

# ── Per-level emoji ───────────────────────────────────────────────────────────
# Two chars wide to keep alignment even when a terminal renders the emoji as 2
# columns wide.
_LEVEL_EMOJI: dict[str, str] = {
    "TRACE":    "🔍 ",
    "DEBUG":    "🐛 ",
    "INFO":     "ℹ️  ",
    "SUCCESS":  "✅ ",
    "WARNING":  "⚠️  ",
    "ERROR":    "❌ ",
    "CRITICAL": "🔥 ",
}

# ── Stderr format ─────────────────────────────────────────────────────────────
_STDERR_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "{extra[emoji]}<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)


class InterceptHandler(logging.Handler):
    """Route stdlib ``logging`` records into loguru.

    Attach once to the stdlib root logger::

        logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    After that every ``logging.getLogger(name).info(...)`` call (including
    aiogram, SQLAlchemy, uvicorn, aiohttp internal loggers) is forwarded to
    loguru — with the correct call-site location preserved.
    """

    def emit(self, record: logging.LogRecord) -> None:
        # Resolve the loguru level name; fall back to numeric level on unknown names.
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Walk the call stack up past logging's own internals so loguru
        # reports the real caller (the code that called logging.info / logger.info).
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back  # type: ignore[assignment]
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def _emoji_patcher(record: "Record") -> None:
    """Inject per-level emoji into ``extra`` before the record hits any sink."""
    record["extra"]["emoji"] = _LEVEL_EMOJI.get(record["level"].name, "   ")


import functools
import inspect

def log_error(level="ERROR", default_return=None):
    """Decorator to log exceptions transparently without crashing the app."""
    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.opt(depth=1, exception=True).log(level, f"Unhandled exception in {func.__name__}: {e}")
                return default_return

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.opt(depth=1, exception=True).log(level, f"Unhandled exception in {func.__name__}: {e}")
                return default_return

        return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper
    return decorator

def setup_logging(level: str = "INFO") -> None:
    """Configure loguru as the sole logging backend.

    Steps
    -----
    1. Remove all existing loguru sinks (clean slate).
    2. Register a global patcher that injects per-level emoji into ``extra``.
    3. Add a colourised, human-readable **stderr** sink.
    4. Install ``InterceptHandler`` on the stdlib root logger so every
       third-party library that still calls ``logging.getLogger(...)`` is
       automatically forwarded to loguru.
    5. Silence exceptionally noisy low-level async loggers that produce
       unhelpful DEBUG spam (asyncio, aiormq, aio_pika, aiohttp.access).

    Parameters
    ----------
    level:
        Minimum log level for the stderr sink (default ``"INFO"``).
        Pass ``"DEBUG"`` during development.
    """
    logger.remove()

    # Patcher runs before the record reaches any sink.
    logger.configure(patcher=_emoji_patcher)

    logger.add(
        sys.stderr,
        level=level,
        format=_STDERR_FORMAT,
        colorize=True,
        backtrace=True,   # show full traceback on exceptions
        diagnose=True,    # show variable values in tracebacks (disable in prod if desired)
        enqueue=False,    # synchronous – stderr writes are fast
    )

    # Intercept the stdlib root logger.
    # ``level=0`` means "let every record through"; loguru filters by its own level.
    # ``force=True`` removes any existing handlers (e.g. the default lastResort handler).
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # Silence noisy low-level async internals that flood output at DEBUG.
    for _noisy in ("asyncio", "aiormq", "aio_pika", "aiohttp.access"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)

    logger.success("Loguru initialised  level={}", level)
