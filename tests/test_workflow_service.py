from src.database.models.enums import SubmissionStatus
from src.services.workflow_service import WorkflowService


def test_transition_pending_to_in_review_allowed() -> None:
    assert WorkflowService.can_transition(SubmissionStatus.PENDING, SubmissionStatus.IN_REVIEW) is True


def test_transition_in_review_to_accepted_allowed() -> None:
    assert WorkflowService.can_transition(SubmissionStatus.IN_REVIEW, SubmissionStatus.ACCEPTED) is True


def test_transition_pending_to_accepted_forbidden() -> None:
    assert WorkflowService.can_transition(SubmissionStatus.PENDING, SubmissionStatus.ACCEPTED) is False


def test_transition_accepted_to_in_review_forbidden() -> None:
    assert WorkflowService.can_transition(SubmissionStatus.ACCEPTED, SubmissionStatus.IN_REVIEW) is False


def test_transition_in_review_to_rejected_allowed() -> None:
    assert WorkflowService.can_transition(SubmissionStatus.IN_REVIEW, SubmissionStatus.REJECTED) is True


def test_transition_pending_to_blocked_forbidden() -> None:
    assert WorkflowService.can_transition(SubmissionStatus.PENDING, SubmissionStatus.BLOCKED) is False
