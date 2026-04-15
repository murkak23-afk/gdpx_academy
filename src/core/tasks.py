import asyncio
import logging
from datetime import datetime, timedelta, timezone
from arq import cron
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.config import get_settings
from src.database.session import SessionFactory
from src.domain.submission.submission_service import SubmissionService

logger = logging.getLogger("arq.worker")

async def startup(ctx):
    """Инициализация ресурсов воркера."""
    logger.info("Initializing ARQ Worker...")
    ctx['session_factory'] = SessionFactory
    settings = get_settings()
    
    from aiogram import Bot
    from aiogram.enums import ParseMode
    from aiogram.client.default import DefaultBotProperties
    
    token = settings.bot_token.get_secret_value() if hasattr(settings.bot_token, "get_secret_value") else settings.bot_token
    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    ctx['bot'] = bot

async def shutdown(ctx):
    """Закрытие ресурсов воркера."""
    bot = ctx.get('bot')
    if bot:
        await bot.session.close()

# -----------------
# ЗАДАЧИ ПО РАСПИСАНИЮ (CRON)
# -----------------

async def run_sla_and_autofix_task(ctx):
    """
    Мониторинг SLA и авто-фикс зависших заявок.
    (Заменяет run_in_review_stuck_monitor)
    """
    logger.info("Starting SLA and Auto-Fix task...")
    bot = ctx['bot']
    session_factory = ctx['session_factory']
    settings = get_settings()
    now = datetime.now(timezone.utc)

    try:
        async with session_factory() as session:
            sub_svc = SubmissionService(session=session)
            
            # 1. Авто-перевод из 'Выданных' в 'Проверку' (Auto-fix)
            threshold_issued = now - timedelta(hours=1)
            try:
                moved_count = await sub_svc.auto_transition_issued_to_verification(threshold_issued)
                if moved_count > 0:
                    logger.info(f"SLA: {moved_count} items auto-moved to confirmation.")
            except AttributeError:
                logger.warning("Метод auto_transition_issued_to_verification ещё не реализован в SubmissionService. Задача пропущена.")
                moved_count = 0
            except Exception as e:
                logger.error(f"Ошибка в auto_transition_issued_to_verification: {e}")
                moved_count = 0

            # 2. Алерты по зависшим IN_REVIEW (SLA Monitoring)
            if settings.moderation_chat_id != 0:
                threshold_review = now - timedelta(minutes=40)
                try:
                    stuck = await sub_svc.list_in_review_stale(threshold_review)

                    for s in stuck:
                        admin = s.admin
                        uname = (admin.username if admin is not None else None) or "unknown"
                        text = f"⚠️ <b>SLA ALERT</b>\nЗаявка #{s.id} зависла у админа @{uname}!"
                        try:
                            from src.core.utils.message_manager import MessageManager
                            mm = MessageManager(bot)
                            await mm.send_notification(user_id=settings.moderation_chat_id, text=text)
                        except Exception as exc:
                            logger.warning(f"Failed to send SLA alert for #{s.id}: {exc}")
                except AttributeError:
                    logger.warning("Метод list_in_review_stale ещё не реализован. Задача SLA пропущена.")
                except Exception as e:
                    logger.error(f"Ошибка в list_in_review_stale: {e}")
            
            await session.commit()
    except Exception:
        logger.exception("Error in run_sla_and_autofix_task")

async def run_daily_cleaner_task(ctx):
    """
    Ежедневная архивация старых заявок.
    (Заменяет run_archiver)
    """
    logger.info("Starting Daily Cleaner (Archive) task...")
    session_factory = ctx['session_factory']
    
    try:
        async with session_factory() as session:
            sub_svc = SubmissionService(session=session)
            try:
                count = await sub_svc.archive_daily_submissions()
                logger.info(f"Daily cleaner: archived {count} submissions.")
            except AttributeError:
                logger.warning("Метод archive_daily_submissions ещё не реализован. Очистка пропущена.")
            await session.commit()
    except Exception:
        logger.exception("Error in run_daily_cleaner_task")

async def run_daily_report_task(ctx):
    """
    Генерация и отправка ежедневного отчета админам.
    """
    logger.info("Starting Daily Report task...")
    bot = ctx['bot']
    session_factory = ctx['session_factory']
    settings = get_settings()
    
    if settings.moderation_chat_id == 0:
        return

    try:
        from src.core.analytics_service import AnalyticsService
        async with session_factory() as session:
            analytics = AnalyticsService(session)
            try:
                report_data = await analytics.get_global_report()
                
                text = (
                    "📊 <b>DAILY SYSTEM REPORT</b>\n"
                    "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰\n"
                    f"Всего заявок: {report_data.esim_accepted + report_data.esim_rejected}\n"
                    f"Принято (24ч): {report_data.turnover_24h} USD\n"
                    f"К выплате: {report_data.pending_payouts_sum} USD"
                )
                from src.core.utils.message_manager import MessageManager
                mm = MessageManager(bot)
                await mm.send_notification(user_id=settings.moderation_chat_id, text=text)
            except Exception as e:
                logger.error(f"Ошибка при генерации отчета: {e}")
    except Exception:
        logger.exception("Error in run_daily_report_task")

async def run_daily_simbuyer_report_task(ctx):
    """
    Рассылка ежедневных отчетов симбайерам по их итогам.
    Пн-Пт: 18:00 МСК, Сб: 16:00 МСК.
    """
    logger.info("Starting Daily Simbuyer Report task...")
    bot = ctx['bot']
    session_factory = ctx['session_factory']
    
    from src.database.models.web_control import DeliveryConfig
    from src.database.models.enums import UserRole, SubmissionStatus
    from sqlalchemy import select, and_, func

    async with session_factory() as session:
        # 1. Получаем всех активных симбайеров
        stmt_users = select(User).where(User.role == UserRole.SIMBUYER, User.is_active.is_(True))
        users = (await session.execute(stmt_users)).scalars().all()
        
        msk_tz = timezone(timedelta(hours=3))
        now_msk = datetime.now(msk_tz)
        start_of_day = now_msk.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_day_utc = start_of_day.astimezone(timezone.utc)

        for user in users:
            try:
                # 2. Считаем итоги за день (МСК)
                stmt_stats = select(
                    func.count(Submission.id),
                    func.coalesce(func.sum(Submission.accepted_amount), 0)
                ).where(
                    Submission.buyer_id == user.id,
                    Submission.status == SubmissionStatus.ACCEPTED,
                    Submission.reviewed_at >= start_of_day_utc
                )
                res = (await session.execute(stmt_stats)).one()
                count, total_sum = res[0], Decimal(res[1])

                if count == 0:
                    continue # Нет смысла слать пустой отчет

                # 3. Ищем куда слать (DeliveryConfig)
                stmt_cfg = select(DeliveryConfig.chat_id).where(DeliveryConfig.user_id == user.id).limit(1)
                chat_id = (await session.execute(stmt_cfg)).scalar()

                if not chat_id:
                    logger.warning(f"No chat_id configured for Simbuyer {user.id}")
                    continue

                text = (
                    f"📊 <b>ИТОГ ЗА ДЕНЬ ({now_msk.strftime('%d.%m.%Y')})</b>\n"
                    f"▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰\n"
                    f"👤 <b>АККАУНТ:</b> {user.full_name}\n"
                    f"✅ <b>ПРИНЯТО:</b> <code>{count} шт.</code>\n"
                    f"💰 <b>К ВЫПЛАТЕ:</b> <code>{total_sum} USDT</code>\n"
                    f"▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰\n"
                    f"💡 <i>Сверка произведена автоматически.</i>"
                )
                
                from src.core.utils.message_manager import MessageManager
                mm = MessageManager(bot)
                await mm.send_notification(user_id=chat_id, text=text)
                logger.info(f"Daily report sent to Simbuyer {user.id} (Chat: {chat_id})")

            except Exception as e:
                logger.error(f"Failed to send daily report to Simbuyer {user.id}: {e}")

# -----------------
# CONFIG
# -----------------

settings = get_settings()
_redis_url = settings.redis_url
if _redis_url and _redis_url.startswith("redis://"):
    _redis_url = _redis_url[8:]
    host_port = _redis_url.split("@")[-1].split("/")[0]
    host, port = host_port.split(":") if ":" in host_port else (host_port, 6379)
else:
    host, port = 'localhost', 6379

class WorkerSettings:
    """ARQ Worker configuration."""
    redis_settings = RedisSettings(host=host, port=int(port))
    on_startup = startup
    on_shutdown = shutdown
    
    cron_jobs = [
        # SLA мониторинг и авто-фикс каждые 10 минут
        cron(run_sla_and_autofix_task, minute=set(range(0, 60, 10))),
        # Архивация в 23:30 MSK (20:30 UTC)
        cron(run_daily_cleaner_task, hour={20}, minute={30}),
        # Отчет для админов в 09:00 MSK (06:00 UTC)
        cron(run_daily_report_task, hour={6}, minute={0}),
        # Отчет для симбайеров (Пн-Пт 18:00 MSK, Сб 16:00 MSK)
        cron(run_daily_simbuyer_report_task, hour={15}, minute={0}, weekday={0,1,2,3,4}),
        cron(run_daily_simbuyer_report_task, hour={13}, minute={0}, weekday={5}),
    ]
