from pathlib import Path

from src.agent import conditions_agent
from src.categories import load_category
from src.services import session_service


ROOT = Path(__file__).resolve().parents[1]


def test_computer_question_is_localized_without_changing_values():
    question = session_service._next_question(
        load_category("computer"),
        {"mode": "build"},
        "en-US",
    )

    assert question["text"] == "What will you mainly use the computer for?"
    assert question["options"] == [
        {"value": "game", "label": "Gaming"},
        {"value": "creation", "label": "Creative work"},
        {"value": "office", "label": "Office work"},
        {"value": "study", "label": "Study"},
        {"value": "other", "label": "Other"},
    ]


def test_computer_summary_fields_are_fully_localized():
    fields = session_service._build_fields(
        load_category("computer"),
        {
            "mode": "build",
            "purpose": "game",
            "budget_max": 2_000_000,
            "priority": "performance",
        },
        "en-US",
    )
    by_key = {field["key"]: field for field in fields}

    assert by_key["mode"]["label"] == "Build type"
    assert by_key["mode"]["display"] == "New computer"
    assert by_key["purpose"]["display"] == "Gaming"
    assert by_key["budget_max"]["display"] == "₩2,000,000"
    assert by_key["priority"]["display"] == "Performance"


def test_all_configured_condition_copy_has_english_variants():
    for category in ("computer", "baby"):
        definition = load_category(category)
        for field in definition["fields"]:
            assert field.get("label_en"), (category, field["key"])
        for question in definition["question_sets"]:
            assert question.get("label_en"), (category, question["id"])
            if question.get("options"):
                assert len(question.get("options_en", [])) == len(question["options"]), (
                    category,
                    question["id"],
                )


def test_existing_exact_assistant_messages_are_localized_on_read():
    definition = load_category("computer")

    assert session_service._localized_assistant_message(
        "주로 어떤 용도로 쓰실 건가요?", definition, "en-US"
    ) == "What will you mainly use the computer for?"
    assert session_service._localized_assistant_message(
        session_service._ALL_SET, definition, "en-US"
    ) == session_service._ALL_SET_EN


def test_english_option_labels_are_accepted_as_answers():
    question = next(q for q in load_category("computer")["question_sets"] if q["id"] == "q_purpose")

    assert session_service._canonicalize_answer_values(question, ["Creative work"]) == ["creation"]


def test_requested_locale_overrides_user_text_language_for_agent_prompt():
    definition = load_category("computer")
    draft = conditions_agent.ConditionDraft(
        category="computer",
        cat_def=definition,
        values={"mode": "build"},
        missing_fn=lambda values: session_service.compute_missing(definition, values),
        next_question_fn=lambda values: session_service._next_question(definition, values, "en-US"),
    )

    prompt = conditions_agent.system_prompt(draft, "200만원", locale="en-US")
    assert prompt.endswith("including the closing question.")
    assert '"What will you mainly use the computer for?"' in prompt


def test_condition_routes_resolve_and_forward_locale():
    source = (ROOT / "src" / "routers" / "session.py").read_text(encoding="utf-8")

    for service_call in (
        "get_session_state(conn, list_id, principal, locale)",
        "body.category, body.mode, principal, locale",
        "body.field, body.value, principal, locale",
        "body.text, principal, locale",
        "body.question_id, body.selected, principal, locale",
        "reset_conditions(conn, list_id, principal, locale)",
        "body.file_name, body.content, principal, locale",
    ):
        assert service_call in source
