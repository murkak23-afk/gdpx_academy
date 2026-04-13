from __future__ import annotations

import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.presentation.filters.admin import IsAdminFilter
from src.domain.finance.cryptobot_service import CryptoBotService

router = Router(name="admin-health-router")

async def _get_health_report(session: AsyncSession) -> str:
    start_time = time.monotonic()
    
    # 1. DB Check
    db_status = "✅ OK"
    db_latency = 0.0
    try:
        db_start = time.monotonic()
        await session.execute(text("SELECT 1"))
        db_latency = (time.monotonic() - db_start) * 1000
    except Exception as e:
        db_status = f"❌ Error: {str(e)[:50]}"

    # 2. CryptoBot Check
    settings = get_settings()
    crypto_status = "⏸ Disabled"
    if settings.crypto_pay_token:
        try:
            crypto_service = CryptoBotService(settings.crypto_pay_token)
            me = await crypto_service.get_me()
            crypto_status = f"✅ OK ({me.name})"
        except Exception as e:
            crypto_status = f"❌ Error: {str(e)[:50]}"

    total_latency = (time.monotonic() - start_time) * 1000

    report = (
        "<b>🏥 System Health Report</b>\n\n"
        f"<b>🗄 Database:</b> {db_status} (<code>{db_latency:.1f}ms</code>)\n"
        f"<b>💎 CryptoPay:</b> {crypto_status}\n"
        f"<b>⏱ Total Latency:</b> <code>{total_latency:.1f}ms</code>\n"
        f"<b>📅 Checked at:</b> <code>{time.strftime('%H:%M:%S')}</code>"
    )
    return report

@router.message(Command("health"), IsAdminFilter())
async def cmd_health(message: Message, session: AsyncSession):
    report = await _get_health_report(session)
    await message.answer(report, parse_mode="HTML")

@router.callback_query(F.data == "admin:health", IsAdminFilter())
async def cb_health(callback: CallbackQuery, session: AsyncSession):
    report = await _get_health_report(session)
    await callback.message.edit_text(report, parse_mode="HTML")
