from src.handlers.moderation_flow import _parse_submission_id_selection


def test_parse_submission_id_selection_list_and_range() -> None:
    pending_by_id = {3: object(), 6: object(), 9: object(), 12: object()}
    result = _parse_submission_id_selection("3-9, 12", pending_by_id)
    assert result == [3, 6, 9, 12]


def test_parse_submission_id_selection_skips_missing_and_duplicates() -> None:
    pending_by_id = {10: object(), 20: object(), 30: object()}
    result = _parse_submission_id_selection("10,20,20,15-25,100", pending_by_id)
    assert result == [10, 20]


def test_parse_submission_id_selection_reversed_range_supported() -> None:
    pending_by_id = {5: object(), 7: object(), 9: object()}
    result = _parse_submission_id_selection("9-5", pending_by_id)
    assert result == [5, 7, 9]
