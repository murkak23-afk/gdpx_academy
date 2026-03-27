from src.main_operators import MAIN_OPERATOR_GROUPS, category_title_to_main_group_label


def test_main_groups_cover_iteration_contract() -> None:
    assert len(MAIN_OPERATOR_GROUPS) >= 1
    for item in MAIN_OPERATOR_GROUPS:
        assert len(item) == 2
        label, keywords = item
        assert isinstance(label, str) and label
        assert isinstance(keywords, frozenset) and keywords


def test_category_title_to_main_group_label_matches() -> None:
    assert category_title_to_main_group_label("МТС eSIM") == "МТС"
    assert category_title_to_main_group_label("Beeline Premium") == "Билайн"
    assert category_title_to_main_group_label("megafon_опт") == "МегаФон"
    assert category_title_to_main_group_label("Теле 2 РФ") == "Теле2"


def test_category_title_to_main_group_label_unknown_returns_none() -> None:
    assert category_title_to_main_group_label("Неизвестный оператор XYZ") is None
