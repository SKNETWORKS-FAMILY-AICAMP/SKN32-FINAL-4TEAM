"""A7 리뷰 폼 계측값 — 정수만 받고, 내용은 못 들어오고, 없으면 키를 만들지 않는다."""
import pytest
from pydantic import ValidationError

from src.schemas import BuildReviewIn, PartReviewIn, ReviewTelemetry
from src.services.review_service import TELEMETRY_KEY, usage_context_with_telemetry


def test_telemetry_accepts_counts_only():
    t = ReviewTelemetry(paste_count=2, paste_chars=340, typing_ms=84_000, edit_count=5, compose_ms=190_000)
    assert t.model_dump() == {"paste_count": 2, "paste_chars": 340, "typing_ms": 84_000,
                              "edit_count": 5, "compose_ms": 190_000}


@pytest.mark.parametrize("bad", [
    {"paste_count": -1},                         # 음수
    {"paste_text": "복사한 본문"},                 # 내용이 들어오는 키 — 거부
    {"keys": ["a", "b"]},                        # 키 입력 로그 — 거부
    {"typing_ms": "fast"},                       # 정수 아님
])
def test_telemetry_rejects_content_and_unknown_keys(bad):
    with pytest.raises(ValidationError):
        ReviewTelemetry(**bad)


def test_review_requests_take_optional_telemetry():
    base = dict(rating=5, title="t", body="b")
    assert PartReviewIn(variant_id="v", **base).telemetry is None
    r = BuildReviewIn(build_version_id="bv", telemetry={"paste_count": 1}, **base)
    assert r.telemetry is not None and r.telemetry.paste_count == 1 and r.telemetry.typing_ms == 0


def test_usage_context_keeps_absence_distinct_from_zero():
    ctx = usage_context_with_telemetry({"usage_days": 30}, None)
    assert ctx == {"usage_days": 30} and TELEMETRY_KEY not in ctx      # 미계측 ≠ 0회
    ctx = usage_context_with_telemetry({"usage_days": 30}, ReviewTelemetry(paste_count=3))
    assert ctx["usage_days"] == 30 and ctx[TELEMETRY_KEY]["paste_count"] == 3
