from __future__ import annotations

import asyncio
import logging
import pickle
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.core.cache import get_redis
from src.core.config import get_settings
from src.database.models.enums import PayoutStatus, RejectionReason, SubmissionStatus
from src.database.models.publication import Payout, PublicationArchive
from src.database.models.submission import ReviewAction, Submission
from src.core.utils.ui_builder import DIVIDER, DIVIDER_LIGHT
from src.core.cache.keyboard_cache import invalidate_kb_cache
from src.core.cache import invalidate_cache_pattern

if TYPE_CHECKING:
    from aiogram import Bot
    from src.database.uow import UnitOfWork

logger = logging.getLogger(__name__)

# Хранилище задач для дебаунса уведомлений (user_id -> Task)
_notif_tasks: Dict[int, asyncio.Task] = {}


class WorkflowService:
    """Единый сервис переходов статусов карточек (Единый Источник Истины)."""

    _ALLOWED: Dict[SubmissionStatus, set[SubmissionStatus]] = {
        SubmissionStatus.PENDING: {
            SubmissionStatus.IN_WORK,
            SubmissionStatus.REJECTED, 
            SubmissionStatus.BLOCKED, 
            SubmissionStatus.NOT_A_SCAN
        },
        SubmissionStatus.IN_WORK: {
            SubmissionStatus.IN_WORK,
            SubmissionStatus.WAIT_CONFIRM,
            SubmissionStatus.PENDING,
            SubmissionStatus.REJECTED,
            SubmissionStatus.BLOCKED,
            SubmissionStatus.NOT_A_SCAN,
        },
        SubmissionStatus.WAIT_CONFIRM: {
            SubmissionStatus.IN_REVIEW,
            SubmissionStatus.PENDING,
            SubmissionStatus.ACCEPTED,
            SubmissionStatus.REJECTED,
            SubmissionStatus.BLOCKED,
            SubmissionStatus.NOT_A_SCAN,
        },
        SubmissionStatus.IN_REVIEW: {
            SubmissionStatus.ACCEPTED,
            SubmissionStatus.REJECTED,
            SubmissionStatus.BLOCKED,
            SubmissionStatus.NOT_A_SCAN,
            SubmissionStatus.PENDING,
        },
    }

    def __init__(self, uow: UnitOfWork | AsyncSession | None = None, session: AsyncSession | None = None) -> None:
        from sqlalchemy.ext.asyncio import AsyncSession
        from src.database.uow import UnitOfWork
        
        if session is not None:
            self._uow = UnitOfWork(session)
        elif isinstance(uow, AsyncSession):
            self._uow = UnitOfWork(uow)
        elif uow is not None:
            self._uow = uow
        else:
            raise ValueError("Either uow or session must be provided")
            
        self._session = self._uow.session  # Для сохранения работы внутренних методов, пока не все перенесены

    @classmethod
    def can_transition(cls, from_status: SubmissionStatus, to_status: SubmissionStatus) -> bool:
        return to_status in cls._ALLOWED.get(from_status, set())

    async def transition(
        self,
        *,
        submission_id: int,
        admin_id: int,
        to_status: SubmissionStatus,
        comment: str | None = None,
        rejection_reason: str | RejectionReason | None = None,
        bot: Optional["Bot"] = None,
        archive_chat_id: int | None = None,
        archive_message_id: int | None = None,
    ) -> Submission | None:
        stmt = (
            select(Submission)
            .options(joinedload(Submission.seller), joinedload(Submission.category))
            .where(Submission.id == submission_id)
        )
        res = await self._session.execute(stmt)
        submission = res.scalar_one_or_none()

        if not submission:
            return None

        from_status = submission.status
        if not self.can_transition(from_status, to_status):
            logger.warning(f"Invalid transition for #{submission_id}: {from_status} -> {to_status}")
            return None

        now = datetime.now(timezone.utc)
        submission.status = to_status
        submission.admin_id = admin_id
        submission.last_status_change = now

        if to_status in {SubmissionStatus.IN_REVIEW, SubmissionStatus.IN_WORK}:
            submission.assigned_at = now
            if to_status == SubmissionStatus.IN_REVIEW and bot and submission.seller:
                await self._send_notification(bot, submission, to_status, None, None)

        elif to_status == SubmissionStatus.PENDING:
            submission.assigned_at = None
            submission.admin_id = None

        elif to_status == SubmissionStatus.ACCEPTED:
            await self._handle_accepted(submission, admin_id, bot, archive_chat_id, archive_message_id)

        elif to_status in {SubmissionStatus.REJECTED, SubmissionStatus.BLOCKED, SubmissionStatus.NOT_A_SCAN}:
            submission.reviewed_at = now
            submission.rejection_reason = rejection_reason if isinstance(rejection_reason, str) else (rejection_reason.value if rejection_reason else None)
            submission.rejection_comment = comment

        self._session.add(
            ReviewAction(
                submission_id=submission.id,
                admin_id=admin_id,
                from_status=from_status,
                to_status=to_status,
                comment=comment,
            )
        )

        if bot and submission.seller:
            await self._send_notification(bot, submission, to_status, rejection_reason, comment)

        await self._session.flush()
        await invalidate_kb_cache() # Инвалидируем при любой смене статуса
        
        # Инвалидируем статистику юзера и лидерборд
        if submission.seller:
            uid = submission.user_id
            tgid = submission.seller.telegram_id
            await invalidate_cache_pattern(f"*u_stats*:{uid}*")
            await invalidate_cache_pattern(f"*user_rank*:{tgid}*")
            await invalidate_cache_pattern(f"*u_rank_pos*:{uid}*")
            await invalidate_cache_pattern(f"*u_profile*:{tgid}*")
            await invalidate_cache_pattern(f"*u_profile*:{uid}*")
        await invalidate_cache_pattern("leaderboard:*")
        
        return submission

    async def bulk_transition(
        self,
        *,
        submission_ids: list[int],
        admin_id: int,
        to_status: SubmissionStatus,
        comment: str | None = None,
        rejection_reason: str | RejectionReason | None = None,
        bot: Optional["Bot"] = None,
    ) -> int:
        count = 0
        for sub_id in submission_ids:
            res = await self.transition(
                submission_id=sub_id,
                admin_id=admin_id,
                to_status=to_status,
                comment=comment,
                rejection_reason=rejection_reason,
                bot=bot
            )
            if res: count += 1
        return count

    async def _handle_accepted(self, sub: Submission, admin_id: int, bot: Bot | None, arc_cid: int | None, arc_mid: int | None):
        now = datetime.now(timezone.utc)
        sub.reviewed_at = now
        
        # [RANK SYSTEM] Вычисляем ранг и бонус
        from src.domain.users.rank_service import RankService
        rank_svc = RankService(self._session)
        user_rank = await rank_svc.get_user_rank(sub.user_id)
        
        base_rate = sub.fixed_payout_rate if sub.fixed_payout_rate > 0 else sub.category.payout_rate
        sub.accepted_amount = rank_svc.calculate_bonus_amount(base_rate, user_rank)
        
        seller = sub.seller
        seller.pending_balance = Decimal(seller.pending_balance or 0) + Decimal(sub.accepted_amount)

        if bot:
            settings = get_settings()
            if settings.moderation_chat_id:
                try:
                    # Добавляем инфо о ранге в лог модерации
                    rank_str = f" [{user_rank.emoji} {user_rank.name}]" if user_rank.bonus_percent > 0 else ""
                    text = (f"✅ <b>eSIM ACCEPTED</b>\n{DIVIDER}\n"
                            f"🔖 <b>ID:</b> <code>#{sub.id}</code>\n"
                            f"👤 <b>Seller ID:</b> <code>{sub.user_id}</code>{rank_str}\n"
                            f"📞 <b>Номер:</b> <code>{sub.phone_normalized or 'N/A'}</code>\n"
                            f"🗂 <b>Категория:</b> <code>{sub.category.title}</code>\n"
                            f"💰 <b>Выплата:</b> <code>{sub.accepted_amount}</code> USDT")
                    
                    # Отправляем сообщение
                    msg = await bot.send_photo(chat_id=settings.moderation_chat_id, photo=sub.telegram_file_id, caption=text, parse_mode="HTML")
                    
                    # Если еще нет архива — создаем запись
                    if not (arc_cid and arc_mid):
                        arc_cid, arc_mid = msg.chat.id, msg.message_id
                except Exception as e:
                    logger.error(f"Failed to send moderation notification for #{sub.id} to {settings.moderation_chat_id}: {e}")

        if arc_cid and arc_mid:
            # Проверяем, нет ли уже такой записи (чтобы не дублировать в PublicationArchive)
            from src.database.models.publication import PublicationArchive
            stmt = select(PublicationArchive).where(PublicationArchive.submission_id == sub.id)
            existing = (await self._session.execute(stmt)).scalar_one_or_none()
            if not existing:
                self._session.add(PublicationArchive(submission_id=sub.id, archive_chat_id=arc_cid, archive_message_id=arc_mid, archived_by_user_id=admin_id))
        
        await self._update_daily_payout(sub)

    async def _update_daily_payout(self, sub: Submission):
        day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        period_key = day_start.date().isoformat()
        stmt = select(Payout).where(Payout.user_id == sub.user_id, Payout.period_key == period_key, Payout.status == PayoutStatus.PENDING, Payout.category_id == sub.category_id)
        res = await self._session.execute(stmt)
        payout = res.scalar_one_or_none()
        if payout:
            payout.amount = Decimal(payout.amount) + Decimal(sub.accepted_amount)
            payout.accepted_count += 1
        else:
            payout = Payout(user_id=sub.user_id, category_id=sub.category_id, amount=sub.accepted_amount, accepted_count=1, period_key=period_key, period_date=day_start.date(), status=PayoutStatus.PENDING, unit_price=sub.accepted_amount)
            self._session.add(payout)

    def _get_status_label(self, status_val: str) -> str:
        """Централизованные красивые лейблы."""
        labels = {
            SubmissionStatus.ACCEPTED.value: "💎 <b>ЗАЧЁТ</b>",
            SubmissionStatus.REJECTED.value: "⚠️ <b>БРАК (ОТКЛОНЕНО)</b>",
            SubmissionStatus.BLOCKED.value: "⛔️ <b>ВАША СИМ-КАРТА ЗАБЛОКИРОВАНА</b>",
            SubmissionStatus.NOT_A_SCAN.value: "📵 <b>НЕ ЧИТАЕТСЯ (НЕ СКАН)</b>",
            SubmissionStatus.IN_REVIEW.value: "🔍 <b>ВЗЯТО НА ПРОВЕРКУ</b>",
        }
        return labels.get(status_val, f"🔘 {status_val.upper()}")

    def _format_event(self, status_val: str, phone: str, reason: str | None) -> str:
        """Форматирует одну строку события."""
        if status_val == SubmissionStatus.BLOCKED.value:
            res = f" 🚫 <b>Номер:</b> <code>{phone}</code>"
            if reason: res += f"\n └ 💬 <b>Причина:</b> <code>{reason}</code>"
            return res
        else:
            res = f" ├ <code>{phone}</code>"
            if reason: res += f"\n └ 💬 <i>Причина: {reason}</i>"
            return res

    async def _send_notification(self, bot: "Bot", sub: Submission, status: SubmissionStatus, reason: str | RejectionReason | None, comment: str | None):
        if status not in {SubmissionStatus.ACCEPTED, SubmissionStatus.REJECTED, SubmissionStatus.BLOCKED, SubmissionStatus.NOT_A_SCAN, SubmissionStatus.IN_REVIEW}:
            return

        user_id, tg_id = sub.user_id, sub.seller.telegram_id
        reason_txt = reason if isinstance(reason, str) else (reason.value if reason else "")
        if comment: reason_txt = f"{reason_txt} ({comment})" if reason_txt else comment
            
        event = {"phone": sub.phone_normalized or f"#{sub.id}", "status": status.value, "reason": reason_txt}

        redis = await get_redis()
        if not redis:
            logger.info(f"Direct notif to {tg_id} (status: {status.value})")
            text = (f"❖ <b>GDPX // УВЕДОМЛЕНИЕ</b>\n{DIVIDER}\n"
                    f"{self._get_status_label(status.value)} (1 шт.)\n"
                    f"{self._format_event(status.value, event['phone'], event['reason'])}\n\n"
                    f"{DIVIDER_LIGHT}\n<i>Ознакомьтесь с деталями выше.</i>")
            try: 
                from src.core.utils.message_manager import MessageManager
                mm = MessageManager(bot)
                await mm.send_notification(user_id=tg_id, text=text, parse_mode="HTML")
            except Exception as e: logger.error(f"Direct notif fail to {tg_id}: {e}")
            return

        cache_key = f"notif_v4:{user_id}"
        try:
            raw = await redis.get(cache_key)
            data = pickle.loads(raw) if raw else {"msg_id": None, "events": []}
            data["events"].append(event)
            await redis.set(cache_key, pickle.dumps(data), ex=3600)
            if user_id in _notif_tasks: _notif_tasks[user_id].cancel()
            _notif_tasks[user_id] = asyncio.create_task(self._flush_notification(user_id, tg_id, bot))
        except Exception as e: logger.error(f"Notif cache error: {e}")

    async def _flush_notification(self, user_id: int, tg_id: int, bot: "Bot"):
        try:
            await asyncio.sleep(1.5)
            redis = await get_redis()
            cache_key = f"notif_v4:{user_id}"
            raw = await redis.get(cache_key) if redis else None
            if not raw: return
            
            data = pickle.loads(raw)
            events = data.get("events", [])
            if not events: return
            
            groups = {}
            for ev in events:
                s = ev["status"]
                if s not in groups: groups[s] = []
                groups[s].append(ev)

            lines = ["❖ <b>GDPX // УВЕДОМЛЕНИЕ</b>", f"{DIVIDER}", ""]
            for s_val, s_items in groups.items():
                lines.append(f"{self._get_status_label(s_val)} (<code>{len(s_items)}</code> шт.)")
                for it in s_items[-15:]:
                    lines.append(self._format_event(s_val, it['phone'], it['reason']))
                lines.append("") 
            
            lines.append(f"{DIVIDER_LIGHT}\n<i>Пожалуйста, ознакомьтесь с деталями выше.</i>")
            text = "\n".join(lines).strip()

            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            from src.presentation.common.factory import NotificationCD
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✖️ ЗАКРЫТЬ УВЕДОМЛЕНИЕ", callback_data=NotificationCD(action="close").pack())]
            ])

            from src.core.utils.message_manager import MessageManager
            mm = MessageManager(bot)
            
            # Вместо прямого редактирования/отправки используем send_notification
            # Но для группировки мы всё равно хотим иметь возможность редактировать!
            # Улучшим send_notification в MessageManager позже, если нужно.
            # Пока что WorkflowService сам управляет группировкой через msg_id.

            msg_id = data.get("msg_id")
            sent = None
            if msg_id:
                try: 
                    sent = await bot.edit_message_text(
                        chat_id=tg_id, 
                        message_id=msg_id, 
                        text=text, 
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
                except Exception: 
                    pass
            
            if not sent:
                # Используем унифицированный метод
                msg_id = await mm.send_notification(
                    user_id=tg_id,
                    text=text,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
                if msg_id:
                    data["msg_id"] = msg_id
                    await redis.set(cache_key, pickle.dumps(data), ex=3600)
                    logger.info(f"Flush notif sent to {tg_id} (msg_id: {msg_id})")
        except asyncio.CancelledError: pass
        except Exception as e: logger.error(f"Flush fail: {e}")
        finally: _notif_tasks.pop(user_id, None)
