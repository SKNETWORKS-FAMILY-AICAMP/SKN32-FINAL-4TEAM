from src.categories import load_category
from src.services.session_service import _canonicalize_answer_values


def test_answer_values_restore_age_chip_integer_from_html_string():
    question = next(q for q in load_category("baby")["question_sets"] if q["id"] == "q_age")

    assert _canonicalize_answer_values(question, ["5"]) == [5]
    assert _canonicalize_answer_values(question, ["4~6개월"]) == [5]


def test_answer_values_restore_boolean_chip_from_html_string():
    question = next(q for q in load_category("baby")["question_sets"] if q["id"] == "q_sitting")

    assert _canonicalize_answer_values(question, ["true"]) == [True]
