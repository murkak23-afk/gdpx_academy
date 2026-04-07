"""One-Tap Deploy — быстрый повтор последнего успешного деплоя eSIM.

Handler
───────
CB_SELLER_DEPLOY_REPEAT → on_deploy_repeat
    FSM Bypass: пропускает шаг выбора категории, восстанавливает контекст
    из User.last_deploy_payload и сразу переходит к загрузке фото (step 2).

Payload shape expected in User.last_deploy_payload:
    {"category_id": int, "label": str}
"""

from __future__ import annotations

from loguru import logger

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from src.keyboards.builders import get_seller_main_kb
from src.keyboards.callbacks import CB_SELLER_DEPLOY_REPEAT
from src.services import CategoryService, UserService
from src.states.submission_state import SubmissionState
from src.utils.fsm_progress import FSMProgressFormatter
from src.utils.text_format import edit_message_text_or_caption_safe

from ._shared import _seller_fsm_cancel_keyboard

router = Router(name="seller-quick-deploy-router")


@router.callback_query(F.data == CB_SELLER_DEPLOY_REPEAT)
async def on_deploy_repeat(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Bypass category selection — drop straight into the photo-upload step."""
    if callback.from_user is None or callback.message is None:
        return

    # ── Load user + payload ───────────────────────────────────────────
    user = await UserService(session=session).get_by_telegram_id(callback.from_user.id)
    if user is None:
        await callback.answer("СНАЧАЛА /START", show_alert=True)
        return

    payload = user.last_deploy_payload
    if not payload or not payload.get("category_id"):
        await callback.answer("ИСТОРИЯ ДЕПЛОЯ ПУСТА", show_alert=True)
        return

    category_id: int = int(payload["category_id"])
    label: str = payload.get("label", "—")

    # ── Verify category is still active ──────────────────────────────
    category = await CategoryService(session=session).get_by_id(category_id)
    if category is None or not category.is_active:
        await callback.answer(
            f"КАТЕГОРИЯ «{label}» НЕДОСТУПНА — ВЫБЕРИ ВРУЧНУЮ",
            show_alert=True,
        )
        # Clear stored payload so stale entry doesn't stay forever.
        await UserService(session=session).save_last_deploy_payload(user.id, {})
        return

    # ── FSM bypass: replicate on_seller_fsm_category_pick state setup ─
    await state.clear()
    await state.update_data(
        category_id=category.id,
        batch_accepted=0,
        batch_rejected=0,
        batch_reject_reasons={},
        batch_rows=[],
        batch_seen_numbers=[],
        batch_seen_file_uids=[],
        batch_status_msg_id=None,
    )
    await state.set_state(SubmissionState.waiting_for_photo)

    # ── Alert + render step 2 ─────────────────────────────────────────
    await callback.answer(f"ВЫБОР ВОССТАНОВЛЕН: {label}", show_alert=True)

    photo_text = FSMProgressFormatter.format_fsm_message(
        current_step=2,
        include_progress_bar=True,
        include_description=True,
        full_description=True,
    )
    await edit_message_text_or_caption_safe(
        callback.message,
        text=photo_text,
        reply_markup=_seller_fsm_cancel_keyboard(),
        parse_mode="HTML",
    )
