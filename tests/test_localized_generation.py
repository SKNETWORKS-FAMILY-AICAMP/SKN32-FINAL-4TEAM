import pytest

from src.clients import llm_client
from src.dto import BuildItem, BuildResult, VerificationResult, VerificationTarget
from src.engine import stage3c_verify, stage5_explain
from src.engine.prompts import (
    EXPLAIN_SYSTEM,
    VERIFY_ISSUE_SYSTEM,
    explain_system,
    verify_issue_system,
)


def _build() -> BuildResult:
    return BuildResult(
        list_id="L",
        items=[
            BuildItem(
                slot="CPU",
                product_key="test-cpu",
                name="Test CPU",
                price=300_000,
                rank_from_3b=1,
            )
        ],
        totals={"price": 300_000},
        budget={"max": 1_000_000},
    )


def test_prompt_builders_select_requested_locale():
    assert "OUTPUT_LOCALE=ko-KR" in VERIFY_ISSUE_SYSTEM
    assert "OUTPUT_LOCALE=ko-KR" in EXPLAIN_SYSTEM
    assert "OUTPUT_LOCALE=en-US" in verify_issue_system("en-US")
    assert "natural American English" in explain_system("en-US")


def test_explanation_prompt_uses_locale_specific_amount_format():
    korean = explain_system("ko-KR")
    english = explain_system("en-US")

    assert "849,000원" in korean
    assert "₩849,000" not in korean
    assert "₩849,000" in english
    assert "849,000원" not in english


def test_english_issue_sentence_uses_english_prompt(monkeypatch):
    captured = {}

    def fake_call(_prompt, *, system=None, **_kwargs):
        captured["system"] = system
        return {"text": "The observed value is 120%."}

    monkeypatch.setattr(stage3c_verify, "call_llm", fake_call)

    text = stage3c_verify._issue_sentence(
        "budget",
        "120%",
        [],
        locale="en-US",
    )

    assert text == "The observed value is 120%."
    assert "OUTPUT_LOCALE=en-US" in captured["system"]


def test_english_issue_sentence_falls_back_in_english(monkeypatch):
    def fail_call(*_args, **_kwargs):
        raise RuntimeError("test failure")

    monkeypatch.setattr(stage3c_verify, "call_llm", fail_call)

    assert stage3c_verify._issue_sentence(
        "budget",
        "120%",
        [],
        locale="en-US",
    ) == "budget: observed value 120%"


@pytest.mark.parametrize("verdict", [
    "This configuration passes.",
    "This configuration pass is valid.",
    "This configuration fails.",
    "This configuration is compliant.",
])
def test_english_verdict_variants_are_rejected(monkeypatch, verdict):
    monkeypatch.setattr(stage3c_verify, "call_llm", lambda *_args, **_kwargs: {"text": verdict})

    assert stage3c_verify._issue_sentence(
        "budget",
        "120%",
        [],
        locale="en-US",
    ) == "budget: observed value 120%"


def test_mock_issue_sentence_uses_requested_locale(monkeypatch):
    monkeypatch.setattr(llm_client, "MOCK_MODE", True)

    result = llm_client.call_llm(
        "test",
        system=verify_issue_system("en-US"),
    )

    assert "observed value" in result["text"]


def test_english_explanation_uses_english_prompt(monkeypatch):
    captured = {}

    def fake_call(_prompt, *, system=None, **_kwargs):
        captured["system"] = system
        return {
            "headline": "Used ₩300,000 with verification confidence 92/100.",
            "items": [
                {
                    "slot": "CPU",
                    "reason": "Test CPU meets the requirements and is ranked #1 at ₩300,000.",
                }
            ],
            "caveats": [],
        }

    monkeypatch.setattr(stage5_explain, "call_llm", fake_call)
    verification = VerificationResult(
        list_id="L",
        category="computer",
        mode="set",
        targets=[VerificationTarget(subject="set", confidence=92, passed=True, rounds=1)],
    )

    draft = stage5_explain._llm_draft(
        _build(),
        verification,
        None,
        lambda *_: None,
        locale="en-US",
    )

    assert draft is not None
    assert "OUTPUT_LOCALE=en-US" in captured["system"]


def test_english_marketing_draft_is_rejected(monkeypatch):
    def fake_call(*_args, **_kwargs):
        return {
            "headline": "A perfect build with verification confidence 92/100.",
            "items": [
                {
                    "slot": "CPU",
                    "reason": "Test CPU is the best choice at ₩300,000.",
                }
            ],
            "caveats": [],
        }

    monkeypatch.setattr(stage5_explain, "call_llm", fake_call)
    verification = VerificationResult(
        list_id="L",
        category="computer",
        mode="set",
        targets=[VerificationTarget(subject="set", confidence=92, passed=True, rounds=1)],
    )

    assert stage5_explain._llm_draft(
        _build(),
        verification,
        None,
        lambda *_: None,
        locale="en-US",
    ) is None


def test_english_headline_without_confidence_is_accepted(monkeypatch):
    # 신뢰도 숫자 누락 시 재시도하던 가드를 뺐다(docs/decisions/0003) — 신뢰도 없는 정상 초안이 채택돼야 한다
    def fake_call(*_args, **_kwargs):
        return {
            "headline": "Used ₩300,000 of the ₩1,000,000 budget.",
            "items": [
                {
                    "slot": "CPU",
                    "reason": "Test CPU meets the requirements and is ranked #1 at ₩300,000.",
                }
            ],
            "caveats": [],
        }

    monkeypatch.setattr(stage5_explain, "call_llm", fake_call)
    verification = VerificationResult(
        list_id="L",
        category="computer",
        mode="set",
        targets=[VerificationTarget(subject="set", confidence=92, passed=True, rounds=1)],
    )

    assert stage5_explain._llm_draft(
        _build(),
        verification,
        None,
        lambda *_: None,
        locale="en-US",
    ) is not None


def test_english_explanation_fallback_is_localized(monkeypatch):
    monkeypatch.setattr(stage5_explain, "_llm_draft", lambda *_args, **_kwargs: None)
    verification = VerificationResult(
        list_id="L",
        category="computer",
        mode="set",
        targets=[
            VerificationTarget(
                subject="set",
                confidence=92,
                passed=True,
                rounds=1,
                gray_axes=["RAG"],
            )
        ],
    )

    explanation = stage5_explain.run(
        _build(),
        verification,
        lambda *_: None,
        locale="en-US",
    )

    # 신뢰도·회색축은 사용자 문장에서 뺐다(docs/decisions/0003)
    assert explanation.headline.startswith("Used ") and explanation.headline.endswith(" budget.")
    assert "confidence" not in explanation.headline and "confidence" not in explanation.summary
    assert explanation.items[0].reason.startswith("Test CPU — meets the requirements, ranked #1, ")
    assert explanation.caveats == []


def test_english_rule_templates_do_not_leave_korean_ui_copy(monkeypatch):
    monkeypatch.setattr(stage5_explain, "_llm_draft", lambda *_args, **_kwargs: None)
    verification = VerificationResult(
        list_id="L",
        category="computer",
        mode="set",
        targets=[
            VerificationTarget(
                subject="set",
                confidence=92,
                passed=True,
                rounds=1,
                gray_axes=["리뷰 진위 (담당 팀원)"],
            )
        ],
    )

    explanation = stage5_explain.run(
        _build(),
        verification,
        lambda *_: None,
        locale="en-US",
    )

    assert explanation.caveats == []          # 회색축 문구는 사용자 문장에서 뺐다(docs/decisions/0003)
    assert stage5_explain._review_line("missing", [], "en")[0].startswith("No review observations (")


@pytest.mark.parametrize(("message", "slots", "expected"), [
    ("Make the graphics card cheaper", {"GPU"}, "GPU"),
    ("Choose a better motherboard", {"메인보드"}, "메인보드"),
    ("Use a cheaper power supply", {"파워"}, "파워"),
])
def test_english_result_message_matches_component_names(message, slots, expected):
    from src.services import recommendation_service

    assert recommendation_service._match_slot(message, slots) == expected
