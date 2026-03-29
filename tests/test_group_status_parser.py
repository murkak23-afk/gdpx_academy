from src.database.models.enums import RejectionReason, SubmissionStatus
from src.handlers.group_queue import _parse_group_status_change_request


def test_parse_group_status_change_request_block() -> None:
    parsed = _parse_group_status_change_request("/simstatus блок +7 (999) 111-22-33")
    assert parsed is not None

    status, reason, phone_norm, comment = parsed
    assert status == SubmissionStatus.BLOCKED
    assert reason == RejectionReason.RULES_VIOLATION
    assert phone_norm == "79991112233"
    assert "79991112233" in comment


def test_parse_group_status_change_request_not_scan_with_tag() -> None:
    parsed = _parse_group_status_change_request("#sim not scan 8-999-222-33-44")
    assert parsed is not None

    status, reason, phone_norm, _ = parsed
    assert status == SubmissionStatus.NOT_A_SCAN
    assert reason == RejectionReason.QUALITY
    assert phone_norm == "79992223344"


def test_parse_group_status_change_request_ignores_plain_text() -> None:
    parsed = _parse_group_status_change_request("блок +79991112233")
    assert parsed is None
