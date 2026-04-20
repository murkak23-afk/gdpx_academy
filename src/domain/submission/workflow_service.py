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
            SubmissionStatus.ACCEPTED,
            SubmissionStatus.REJECTED, 
            SubmissionStatus.BLOCKED, 
            SubmissionStatus.NOT_A_SCAN
        },
        SubmissionStatus.IN_WORK: {
            SubmissionStatus.ACCEPTED,
            SubmissionStatus.WAIT_CONFIRM,
            SubmissionStatus.PENDING,
            SubmissionStatus.REJECTED,
            SubmissionStatus.BLOCKED,
            SubmissionStatus.NOT_A_SCAN,
        },
        SubmissionStatus.WAIT_CONFIRM: {
            SubmissionStatus.ACCEPTED,
            SubmissionStatus.PENDING,
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
                    try:
                        if sub.telegram_file_id:
                            msg = await bot.send_photo(chat_id=settings.moderation_chat_id, photo=sub.telegram_file_id, caption=text, parse_mode="HTML")
                        else:
                            msg = await bot.send_message(chat_id=settings.moderation_chat_id, text=text, parse_mode="HTML")
                        
                        # Если еще нет архива — создаем запись
                        if not (arc_cid and arc_mid):
                            arc_cid, arc_mid = msg.chat.id, msg.message_id
                    except Exception as send_err:
                        logger.warning(f"Could not send accept notification for #{sub.id}: {send_err}")
                except Exception as e:
                    logger.error(f"Failed to process moderation notification for #{sub.id}: {e}")

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
        stmt = (
            select(Payout)
            .where(
                Payout.user_id == sub.user_id, 
                Payout.period_key == period_key, 
                Payout.status == PayoutStatus.PENDING, 
                Payout.category_id == sub.category_id
            )
            .with_for_update()
        )
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
            SubmissionStatus.ACCEPTED.value: "✅ <b>ЗАЧЁТ</b>",
            SubmissionStatus.REJECTED.value: "⚠️ <b>БРАК (ОТКЛОНЕНО)</b>",
            SubmissionStatus.BLOCKED.value: "💀 <b>БЛОК</b>",
            SubmissionStatus.NOT_A_SCAN.value: "🚫 <b>НЕ СКАН</b>",
            SubmissionStatus.IN_REVIEW.value: "🔍 <b>НА ПРОВЕРКЕ</b>",
            SubmissionStatus.PENDING.value: "📦 <b>СКЛАД</b>",
            SubmissionStatus.IN_WORK.value: "📡 <b>В РАБОТЕ...</b>",
            SubmissionStatus.WAIT_CONFIRM.value: "⏳ <b>ОТРАБОТАНА</b>",
        }
        return labels.get(status_val, f"🔘 {status_val.upper()}")

    def _format_event(self, status_val: str, phone: str, reason: str | None) -> str:
        """Форматирует строку для лога (уже не используется для селлеров напрямую)."""
        return f"  ├ Номер: <code>{phone}</code>\n  └ Причина: {reason or 'нет данных'}"

    async def _send_notification(self, bot: "Bot", sub: Submission, status: SubmissionStatus, reason: str | RejectionReason | None, comment: str | None):
        """[DEPRECATED] Уведомления отключены в пользу раздела СОСТОЯНИЕ eSIM."""
        return # Уведомления больше не отправляются селлеру индивидуально

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
            
            # Получаем пользователя для проверки беззвучного режима
            from src.database.models.user import User
            user = await self._session.get(User, user_id)
            is_silent = user.is_silent_mode if user else False

            # Подсчет сводки
            accepted_count = sum(1 for e in events if e["status"] == SubmissionStatus.ACCEPTED.value)
            blocked_count = sum(1 for e in events if e["status"] == SubmissionStatus.BLOCKED.value)

            text = (
                "🔄 <b>GDPX // ОБНОВЛЕНИЕ СТАТУСА</b>\n"
                f"{DIVIDER}\n"
                "По симкам обновился статус в реестре.\n\n"
                f"Краткая сводка: <code>{accepted_count}</code> зачёт / <code>{blocked_count}</code> блоков.\n"
                f"{DIVIDER_LIGHT}\n"
                "<i>Нажмите кнопку ниже для подробностей.</i>"
            )

            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            from src.presentation.common.factory import SellerMenuCD, SellerSettingsCD
            
            buttons = [
                [InlineKeyboardButton(text="🧬 СОСТОЯНИЕ eSIM", callback_data=SellerMenuCD(action="dynamics").pack())]
            ]
            
            # Кнопка отключения звука только если режим НЕ включен
            if not is_silent:
                buttons.append([InlineKeyboardButton(text="🔕 ОТКЛЮЧИТЬ ЗВУК", callback_data=SellerSettingsCD(action="silent_toggle", value="on").pack())])

            kb = InlineKeyboardMarkup(inline_keyboard=buttons)

            # --- SINGLE MESSAGE LOGIC ---
            # Удаляем старое уведомление перед отправкой нового
            msg_id = data.get("msg_id")
            if msg_id:
                try: await bot.delete_message(chat_id=tg_id, message_id=msg_id)
                except: pass

            # Отправляем новое
            sent_msg = await bot.send_message(
                chat_id=tg_id,
                text=text,
                reply_markup=kb,
                parse_mode="HTML",
                disable_notification=is_silent
            )
            
            # Сохраняем ID нового сообщения и очищаем события
            data["msg_id"] = sent_msg.message_id
            data["events"] = [] 
            await redis.set(cache_key, pickle.dumps(data), ex=3600*24)
            
        except asyncio.CancelledError: pass
        except Exception as e: logger.error(f"Flush fail: {e}")
        finally: _notif_tasks.pop(user_id, None)
