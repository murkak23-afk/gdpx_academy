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
    ТЗ: Пн-Пт 18:00 МСК, Сб 16:00 МСК.
    """
    logger.info("Starting Simbuyer Payout Notifications task...")
    bot = ctx['bot']
    session_factory = ctx['session_factory']
    
    # Статистика за текущий день по МСК (UTC+3)
    msk_tz = timezone(timedelta(hours=3))
    now_msk = datetime.now(msk_tz)
    today_start_msk = now_msk.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start_msk.astimezone(timezone.utc)

    try:
        async with session_factory() as session:
            from src.database.models.web_control import DeliveryConfig
            from src.database.models.submission import Submission
            from src.database.models.enums import SubmissionStatus
            from src.database.models.user import User
            from sqlalchemy import select, func, and_

            # 1. Находим всех активных байеров, у которых есть конфигурация доставки
            stmt = select(User).where(User.role == "simbuyer")
            users = (await session.execute(stmt)).scalars().all()

            for target_user in users:
                # 2. Считаем сумму "Зачётов" для этого байера за сегодня по МСК
                stats_stmt = select(
                    func.count(Submission.id),
                    func.sum(Submission.purchase_price)
                ).where(
                    and_(
                        Submission.buyer_id == target_user.id,
                        Submission.status == SubmissionStatus.ACCEPTED,
                        Submission.updated_at >= today_start_utc
                    )
                )
                
                res = (await session.execute(stats_stmt)).one()
                count, total_amount = res[0] or 0, res[1] or 0

                if count > 0:
                    # 3. Ищем, куда слать отчет (General топик или первый попавшийся чат байера)
                    cfg_stmt = select(DeliveryConfig).where(DeliveryConfig.user_id == target_user.id).limit(1)
                    cfg = (await session.execute(cfg_stmt)).scalar_one_or_none()
                    
                    if not cfg:
                        logger.warning(f"No delivery config for simbayer @{target_user.username}. Cannot send report.")
                        continue

                    text = (
                        "📄 <b>ЕЖЕДНЕВНЫЙ СЧЁТ НА ОПЛАТУ</b>\n"
                        "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰\n"
                        f"👤 Клиент: @{target_user.username or target_user.full_name}\n"
                        f"✅ Успешных сканов: <b>{count} шт.</b>\n"
                        f"💰 Итого к оплате: <b>{total_amount} USDT</b>\n"
                        "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰\n"
                        "<i>Счёт сформирован за текущие сутки (МСК). Пожалуйста, произведите оплату по реквизитам.</i>"
                    )
                    
                    try:
                        # Шлем в General топик (thread_id=None или 0 обычно в General, если не настроено иначе)
                        # В ТЗ: "в главный топик этого чата (general)"
                        await bot.send_message(
                            chat_id=cfg.chat_id, 
                            text=text, 
                            message_thread_id=None # General topic
                        )
                        logger.info(f"Payout notification sent to Chat {cfg.chat_id} for Simbayer {target_user.id}")
                    except Exception as e:
                        logger.error(f"Failed to send payout notification to {cfg.chat_id}: {e}")
            
            await session.commit()
    except Exception:
        logger.exception("Error in run_simbuyer_payout_notifications_task")

# -----------------
# ФОНОВЫЕ ЗАДАЧИ (ON-DEMAND)
# -----------------

async def process_delivery_task(ctx, category_id: int, buyer_id: int, chat_id: int, thread_id: int, item_ids: list[int]):
    """
    Фоновая задача выдачи eSIM через ARQ.
    Гарантирует доставку даже при перезагрузке сервера.
    """
    bot = ctx['bot']
    session_factory = ctx['session_factory']
    
    if not item_ids:
        return

    logger.info(f"ARQ: Starting delivery of {len(item_ids)} items to Buyer {buyer_id} in Chat {chat_id}")

    async with session_factory() as session:
        from sqlalchemy.orm import joinedload
        from src.database.models.submission import Submission
        from src.database.models.web_control import SimbuyerPrice
        from src.database.models.enums import SubmissionStatus
        from sqlalchemy import select, and_
        
        # Загружаем уже забронированные товары
        stmt = select(Submission).options(joinedload(Submission.category)).where(Submission.id.in_(item_ids))
        items = list((await session.execute(stmt)).scalars().all())

        if not items:
            logger.warning(f"ARQ: Items not found in DB (IDS: {item_ids}). Delivery cancelled.")
            return

        # Получаем персональную цену
        price_stmt = select(SimbuyerPrice.price).where(
            and_(SimbuyerPrice.user_id == buyer_id, SimbuyerPrice.category_id == category_id)
        )
        price_val = (await session.execute(price_stmt)).scalar() or 0

        from src.domain.submission.workflow_service import WorkflowService
        from src.database.models.enums import SubmissionStatus
        workflow = WorkflowService(session=session)

        for item in items:
            # Обновляем поля, специфичные для байера
            item.buyer_id = buyer_id
            item.purchase_price = price_val
            item.delivered_to_chat = chat_id
            item.delivered_to_thread = thread_id
            
            # Используем WorkflowService для перехода статуса (это создаст ReviewAction)
            # В качестве admin_id используем buyer_id, так как это действие совершено по его инициативе
            await workflow.transition(
                submission_id=item.id,
                admin_id=buyer_id,
                to_status=SubmissionStatus.IN_WORK,
                comment="Автоматическая выдача через ARQ"
            )

            try:
                cat_title = item.category.title if item.category else "Unknown Cluster"
                arrival_time = item.created_at.strftime('%d.%m.%Y %H:%M')
                caption = (
                    f"<b>GDPX // {cat_title}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n\n"
                    f"🆔 <b>ID:</b> #{item.id}\n"
                    f"📱 <b>НОМЕР:</b> <code>{item.phone_normalized or 'N/A'}</code>\n"
                    f"🕒 <b>ПОСТУПИЛА:</b> {arrival_time}\n\n"
                    f"🍀 <i>Удачного скана и отработки материала!</i>"
                )
                
                await bot.send_photo(
                    chat_id=chat_id, 
                    photo=item.telegram_file_id, 
                    caption=caption, 
                    message_thread_id=thread_id if thread_id != 0 else None,
                )
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(f"ARQ: SEND ERROR (Submission #{item.id}): {e}")
        
        await session.commit()
        logger.info(f"ARQ: Successfully delivered {len(items)} items to chat {chat_id}")

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
    
    functions = [process_delivery_task]
    
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
