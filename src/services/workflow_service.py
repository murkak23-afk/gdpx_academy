from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.enums import RejectionReason, SubmissionStatus
from src.database.models.submission import ReviewAction, Submission


class WorkflowService:
    """Единый сервис переходов статусов карточек."""

    _ALLOWED: dict[SubmissionStatus, set[SubmissionStatus]] = {
        SubmissionStatus.PENDING: {SubmissionStatus.IN_REVIEW, SubmissionStatus.REJECTED},
        SubmissionStatus.IN_REVIEW: {
            SubmissionStatus.ACCEPTED,
            SubmissionStatus.REJECTED,
            SubmissionStatus.BLOCKED,
            SubmissionStatus.NOT_A_SCAN,
        },
    }

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @classmethod
    def can_transition(cls, from_status: SubmissionStatus, to_status: SubmissionStatus) -> bool:
        """Проверяет, допустим ли переход статуса."""

        return to_status in cls._ALLOWED.get(from_status, set())

    async def transition(
        self,
        *,
        submission_id: int,
        admin_id: int,
        to_status: SubmissionStatus,
        comment: str | None = None,
        rejection_reason: RejectionReason | None = None,
    ) -> Submission | None:
        """Выполняет валидный переход статуса и пишет ReviewAction."""

        submission = await self._session.get(Submission, submission_id)
        if submission is None:
            return None

        from_status = submission.status
        if not self.can_transition(from_status, to_status):
            return None

        now = datetime.now(timezone.utc)
        submission.status = to_status
        submission.admin_id = admin_id

        if to_status == SubmissionStatus.IN_REVIEW:
            submission.assigned_at = now

        if to_status in {
            SubmissionStatus.ACCEPTED,
            SubmissionStatus.REJECTED,
            SubmissionStatus.BLOCKED,
            SubmissionStatus.NOT_A_SCAN,
        }:
            submission.reviewed_at = now
            submission.finalized_at = now
            submission.finalized_by_admin_id = admin_id
            submission.final_reason = comment
            if to_status in {
                SubmissionStatus.REJECTED,
                SubmissionStatus.BLOCKED,
                SubmissionStatus.NOT_A_SCAN,
            }:
                submission.rejection_reason = rejection_reason or RejectionReason.OTHER
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
        await self._session.commit()
        await self._session.refresh(submission)
        return submission
