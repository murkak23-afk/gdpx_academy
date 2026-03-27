from src.handlers.moderation_flow import _decode_worked_query, _encode_worked_query


def test_worked_query_encode_decode_roundtrip_credit() -> None:
    raw = _encode_worked_query("credit", seller_id=123, category_id=7, date_from=None)
    tab, seller_id, category_id, date_from = _decode_worked_query(raw)
    assert tab == "credit"
    assert seller_id == 123
    assert category_id == 7
    assert date_from is None


def test_worked_query_decode_invalid_tab_fallbacks_to_credit() -> None:
    tab, seller_id, category_id, date_from = _decode_worked_query("t=bad|s=1|c=2|d=")
    assert tab == "credit"
    assert seller_id == 1
    assert category_id == 2
    assert date_from is None
