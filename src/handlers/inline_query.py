"""Inline query handler: поиск товаров от имени бота при @bot_name + query."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.submission_service import SubmissionService

router = Router(name="inline-query-router")


def _format_inline_result_title(submission) -> str:
    """Форматирует заголовок результата inline query."""
    
    phone = submission.description_text or "н/д"
    category = submission.category.title if submission.category else "н/д"
    seller_obj = submission.seller
    if seller_obj is not None and seller_obj.username:
        seller = f"@{seller_obj.username}"
    elif seller_obj is not None:
        seller = f"@{seller_obj.telegram_id}"
    else:
        seller = f"@{submission.user_id}"
    
    return f"☑️ {phone} | {category} | {seller}"


def _format_inline_result_description(submission) -> str:
    """Форматирует описание результата inline query."""
    
    status = submission.status.value if submission.status else "неизвестно"
    file_type = "\U0001f4f7 Фото" if submission.attachment_type == "photo" else "\U0001f4e6 Архив"
    
    return f"{file_type} | Статус: {status} | ID: {submission.id}"


@router.inline_query()
async def on_inline_search(
    query: InlineQuery,
    session: AsyncSession,
    bot: Bot,
) -> None:
    """Поиск товаров по номеру телефона в inline mode.
    
    Пример: пользователь пишет "@bot_name 234567" → показываем TOP-5 товаров
    """
    
    if not query.query.strip():
        # Пустой запрос - просто отвечаем пусто
        await query.answer(results=[], cache_time=0, is_personal=False)
        return

    search_query = query.query.strip()
    
    # Ищем по сервису
    submissions = await SubmissionService(session).search_by_phone_partial(
        query=search_query,
        limit=5,
    )
    
    # Если ничего не нашли
    if not submissions:
        empty_result = [
            InlineQueryResultArticle(
                id="no_results",
                title="❌ Товаров не найдено",
                description=f'По запросу "{search_query}" ничего не найдено',
                input_message_content=InputTextMessageContent(
                    message_text="❌ По вашему запросу товары не найдены.",
                ),
            )
        ]
        await query.answer(results=empty_result, cache_time=300, is_personal=False)
        return

    # Форматируем результаты
    results = []
    for idx, submission in enumerate(submissions, 1):
        result = InlineQueryResultArticle(
            id=str(submission.id),
            title=_format_inline_result_title(submission),
            description=_format_inline_result_description(submission),
            input_message_content=InputTextMessageContent(
                message_text=(
                    (
                        f"<b>Товар #{submission.id}</b>\n"
                        f"<code>{submission.description_text}</code>\n"
                        f"Категория: {submission.category.title}\n"
                        f"Статус: {submission.status.value}\n"
                        f"Продавец: @{submission.seller.username}"
                    )
                    if submission.seller is not None and submission.seller.username
                    else (
                        f"<b>Товар #{submission.id}</b>\n"
                        f"<code>{submission.description_text}</code>\n"
                        f"Категория: {submission.category.title}\n"
                        f"Статус: {submission.status.value}\n"
                        f"Продавец: @{submission.seller.telegram_id if submission.seller is not None else submission.user_id}"
                    )
                ),
                parse_mode="HTML",
            ),
            thumbnail_url=None,  # Если нужны миниатюры, можно добавить генерацию
        )
        results.append(result)
    
    # Отправляем результаты
    await query.answer(
        results=results,
        cache_time=300,  # Кэшируем на 5 минут
        is_personal=False,  # Результаты видны всем
    )
