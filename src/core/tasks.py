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
                    f"Всего заявок: {report_data.total_submissions}\n"
                    f"Ожидают: {report_data.pending_count}\n"
                    f"Принято (24ч): {report_data.accepted_24h}\n"
                    f"Выплачено: {report_data.total_payouts_volume} USD"
                )
                from src.core.utils.message_manager import MessageManager
                mm = MessageManager(bot)
                await mm.send_notification(user_id=settings.moderation_chat_id, text=text)
            except AttributeError:
                logger.warning("Метод get_global_report ещё не реализован. Отчет пропущен.")
            except Exception as e:
                logger.error(f"Ошибка при генерации отчета: {e}")
    except Exception:
        logger.exception("Error in run_daily_report_task")

async def run_simbuyer_payout_notifications_task(ctx):
    """
    Уведомление Simbuyer-ов об общей сумме выплат за день.
    ТЗ: Пн-Пт 18:00 МСК (15:00 UTC), Сб 16:00 МСК (13:00 UTC).
    """
    logger.info("Starting Simbuyer Payout Notifications task...")
    bot = ctx['bot']
    session_factory = ctx['session_factory']
    now_utc = datetime.now(timezone.utc)
    
    # Определяем начало текущего дня для статистики
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        async with session_factory() as session:
            from src.database.models.web_control import DeliveryConfig
            from src.database.models.submission import Submission
            from src.database.models.enums import SubmissionStatus
            from sqlalchemy import select, func

            # 1. Получаем список всех уникальных маршрутов (Simbuyer -> Chat)
            # Мы группируем по chat_id и user_id, чтобы отправить одно сводное сообщение на чат
            stmt = select(
                DeliveryConfig.user_id, 
                DeliveryConfig.chat_id, 
                DeliveryConfig.thread_id
            ).group_by(DeliveryConfig.user_id, DeliveryConfig.chat_id, DeliveryConfig.thread_id)
            
            configs = (await session.execute(stmt)).all()

            for cfg in configs:
                user_id, chat_id, thread_id = cfg
                
                # 2. Считаем сумму "Зачётов" для этого пользователя за сегодня
                # Важно: ищем по delivered_to_chat, так как это связка с конкретным Simbuyer-ом
                # (предполагаем, что у каждого Simbuyer свой уникальный telegram_id, который и есть в delivered_to_chat)
                from src.database.models.user import User
                target_user = await session.get(User, user_id)
                if not target_user: continue

                stats_stmt = select(
                    func.count(Submission.id),
                    func.sum(Submission.purchase_price)
                ).where(
                    Submission.delivered_to_chat == target_user.telegram_id,
                    Submission.status == SubmissionStatus.ACCEPTED,
                    Submission.updated_at >= today_start
                )
                
                res = (await session.execute(stats_stmt)).one()
                count, total_amount = res[0] or 0, res[1] or 0

                if count > 0:
                    text = (
                        "📄 <b>ЕЖЕДНЕВНЫЙ СЧЁТ НА ОПЛАТУ</b>\n"
                        "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰\n"
                        f"👤 Клиент: @{target_user.username or target_user.full_name}\n"
                        f"✅ Успешных сканов: <b>{count} шт.</b>\n"
                        f"💰 Итого к оплате: <b>{total_amount} USDT</b>\n"
                        "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰\n"
                        "<i>Счёт сформирован за текущие сутки. Пожалуйста, произведите оплату по реквизитам.</i>"
                    )
                    try:
                        # thread_id (General) обычно 0 или 1, но в ТЗ указан конкретный General
                        await bot.send_message(chat_id, text, message_thread_id=thread_id)
                        logger.info(f"Payout notification sent to Chat {chat_id} for User {user_id}")
                    except Exception as e:
                        logger.error(f"Failed to send payout notification to {chat_id}: {e}")
            
            await session.commit()
    except Exception:
        logger.exception("Error in run_simbuyer_payout_notifications_task")

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
        # Отчет в 09:00 MSK (06:00 UTC)
        cron(run_daily_report_task, hour={6}, minute={0}),
        # Уведомления о выплатах Пн-Пт 18:00 (15:00 UTC)
        cron(run_simbuyer_payout_notifications_task, weekday={0,1,2,3,4}, hour={15}, minute={0}),
        # Уведомления о выплатах Сб 16:00 (13:00 UTC)
        cron(run_simbuyer_payout_notifications_task, weekday={5}, hour={13}, minute={0}),
    ]
