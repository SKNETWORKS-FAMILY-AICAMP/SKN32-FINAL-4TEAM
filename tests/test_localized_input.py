import pytest

from src.engine.slot_rules import extract_baby, extract_computer
from src.services import recommendation_service


@pytest.mark.parametrize(("message", "expected"), [
    (
        "I need a quiet gaming PC for ₩1,500,000 at 1440p 165Hz",
        {
            "budget_max": 1_500_000,
            "purpose": "game",
            "priority": "quiet",
            "resolution": "QHD_165",
        },
    ),
    (
        "A 1.2 million won computer for video editing with strong performance",
        {"budget_max": 1_200_000, "purpose": "creation", "priority": "performance"},
    ),
])
def test_english_computer_message_extracts_conditions(message, expected):
    assert extract_computer(message) == expected


def test_english_baby_message_extracts_conditions():
    extracted = extract_baby(
        "My baby is 12 months old. We need feeding bottles, diapers, sleep items and a stroller. "
        "The baby has sensitive skin. Budget is 500 thousand won."
    )

    assert extracted["age_months"] == 12
    assert extracted["budget_max"] == 500_000
    assert extracted["health_skin"] == ["민감성 피부"]
    assert extracted["needs"] == ["수유", "수면", "외출", "기저귀"]


@pytest.mark.parametrize(("message", "expected"), [
    ("Make the GPU cheaper", "cheaper"),
    ("Choose a better processor", "pricier"),
    ("그래픽카드를 더 저렴하게 바꿔줘", "cheaper"),
    ("CPU를 더 좋은 걸로 바꿔줘", "pricier"),
    ("Tell me about the GPU", None),
])
def test_result_change_direction_is_bilingual(message, expected):
    assert recommendation_service._result_change_direction(message) == expected


@pytest.mark.parametrize("message", [
    "이 구성 총평 알려줘",
    "전체 평가를 요약해 줘",
    "Give me an overall assessment of this build",
    "Show me a summary",
])
def test_result_summary_request_is_bilingual(message):
    assert recommendation_service._is_result_summary_request(message)


def test_result_summary_message_returns_saved_explanation(monkeypatch):
    stored = {"explanation": {"status": "ready", "text": "The parts are well balanced."}}
    monkeypatch.setattr(
        recommendation_service,
        "_require_done_run",
        lambda conn, revision_id: (object(), {"id": "run-1"}),
    )
    monkeypatch.setattr(recommendation_service, "get_stored_result", lambda conn, revision_id: stored)

    out = recommendation_service.handle_result_message(
        None,
        None,
        "Give me an overall assessment of this build",
        locale="en-US",
    )

    assert out == {"reply": "The parts are well balanced.", "result": stored}


def test_result_summary_message_has_localized_pending_reply(monkeypatch):
    stored = {"explanation": {"status": "pending", "text": None}}
    monkeypatch.setattr(
        recommendation_service,
        "_require_done_run",
        lambda conn, revision_id: (object(), {"id": "run-1"}),
    )
    monkeypatch.setattr(recommendation_service, "get_stored_result", lambda conn, revision_id: stored)

    out = recommendation_service.handle_result_message(
        None,
        None,
        "Show me a summary",
        locale="en-US",
    )

    assert out["reply"] == "The overall assessment is still being prepared. Please try again shortly."
