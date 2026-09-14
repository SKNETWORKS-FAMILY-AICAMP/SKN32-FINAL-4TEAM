from src.categories import load_category
from src.services.session_service import _canonicalize_answer_values, _display


def test_answer_values_restore_age_chip_integer_from_html_string():
    question = next(q for q in load_category("baby")["question_sets"] if q["id"] == "q_age")

    assert _canonicalize_answer_values(question, ["5"]) == [5]
    assert _canonicalize_answer_values(question, ["4~6개월"]) == [5]


def test_answer_values_restore_boolean_chip_from_html_string():
    question = next(q for q in load_category("baby")["question_sets"] if q["id"] == "q_sitting")

    assert _canonicalize_answer_values(question, ["true"]) == [True]


def test_baby_explicit_empty_answers_keep_a_confirmed_display_value():
    # _display's 3rd positional param is `locale` (develop's i18n refactor,
    # 2026-09-14) — pass it by keyword to avoid re-breaking on a future signature
    # reorder the way this test previously did (it used to pass a `values` dict
    # positionally where `locale` now sits).
    assert _display({"key": "health_skin"}, []) == "특이사항 없음"
    assert _display({"key": "owned_items"}, [], locale="en-US") == "None owned"
    assert _display({"key": "health_skin"}, None) is None
