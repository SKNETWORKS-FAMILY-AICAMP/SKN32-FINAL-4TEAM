"""API 요청/응답 모델 (pydantic).

엔진 내부 DTO(src/dto.py)와 분리한다 — API 계약은 프론트와 협의 후 확정(기획서 §18-1).
지금은 골격만. 필드는 화면흐름 명세 기준 최소.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ── auth ──
class RequestCodeIn(BaseModel):
    email: str


class VerifyCodeIn(BaseModel):
    email: str
    code: str


class TokenOut(BaseModel):
    token: str


# ── session (S1~S3) ──
class SessionOut(BaseModel):
    list_id: str


class CategoryIn(BaseModel):
    category: Literal["computer", "baby"]
    mode: Optional[str] = None


class MessageIn(BaseModel):
    text: str = Field(max_length=500)


class AnswerIn(BaseModel):
    question_id: str
    selected: list[Any]


class SlotPatchIn(BaseModel):
    field: str
    value: Any | None = None


# ── 조건 대화 (§D-4-1) ──
class MessageOut(BaseModel):
    id: str
    role: str
    text: str
    created_at: str


class FieldOut(BaseModel):
    key: str
    label: str
    value: Any = None
    display: str | None = None
    status: str            # confirmed | assumed | missing
    editable: bool = True


class NextQuestionOut(BaseModel):
    id: str
    field: str
    text: str
    select: str             # single | multi | free
    options: list[dict] = Field(default_factory=list)


class ConditionState(BaseModel):
    list_id: str
    category: str | None = None
    messages: list[MessageOut] = Field(default_factory=list)
    fields: list[FieldOut] = Field(default_factory=list)
    next_question: NextQuestionOut | None = None
    can_recommend: bool = False
    accepts_spec_file: bool = False


# ── recommend / result (§D-4-2) ──
class RecommendIn(BaseModel):
    strategy: Optional[Literal["default", "alternative"]] = "default"


class RecommendAcceptedOut(BaseModel):
    """POST /recommend 의 202 응답 — 실행을 접수했을 뿐, 결과는 GET /result 로 폴링."""

    run_id: str
    status: str = "running"


class ProgressStepOut(BaseModel):
    step: str
    label: str
    status: str          # done | running | pending


class TextStatusOut(BaseModel):
    """LLM 등 비동기로 채워지는 문장 필드 공통 모양."""

    status: str           # pending | ready | failed
    text: str | None = None


class ExplanationOut(BaseModel):
    status: str            # pending | ready | failed
    headline: str | None = None
    text: str | None = None


class ProductOut(BaseModel):
    product_key: str
    variant_id: str | None = None
    name: str
    brand: str = ""
    spec_summary: str | None = None
    image_url: str | None = None
    purchase_url: str | None = None


class ReviewBriefOut(BaseModel):
    total_count: int
    excluded_ratio: float
    rating_refined: float


class ItemOut(BaseModel):
    item_id: str
    slot: str
    slot_label: str
    product: ProductOut
    price: int
    price_source: str = "synthetic"       # synthetic | observed
    price_observed_at: str | None = None
    qty: int = 1
    selected: bool = True
    timing: str = "now"                    # now | soon | later
    budget_share: float | None = None
    review: ReviewBriefOut | None = None
    reason: TextStatusOut
    checks: TextStatusOut
    alternatives_count: int = 0


class TotalsOut(BaseModel):
    selected_price: int
    selected_units: int
    budget_remaining: int | None = None
    over_budget: bool = False


class VerificationIssueOut(BaseModel):
    axis: str
    severity: str            # minor | major
    text: str


class VerificationOut(BaseModel):
    status: str               # pending | ready | failed
    confidence: int | None = None
    issues: list[VerificationIssueOut] = Field(default_factory=list)


class RecommendErrorOut(BaseModel):
    code: str
    message: str


class RecommendResultOut(BaseModel):
    """저장된 추천 실행 결과의 공개 API 계약 (docs/frontend_외부수정요청.md §D-4-2)."""

    list_id: str
    run_id: str
    status: str                      # running | done | failed
    progress: list[ProgressStepOut] = Field(default_factory=list)
    category: str
    conditions_summary: str = ""
    budget_max: int | None = None
    items: list[ItemOut] = Field(default_factory=list)
    totals: TotalsOut | None = None
    verification: VerificationOut = Field(default_factory=lambda: VerificationOut(status="pending"))
    explanation: ExplanationOut = Field(default_factory=lambda: ExplanationOut(status="pending"))
    reasoning_log: list[dict] = Field(default_factory=list)
    data_notice: str = "상품·가격·리뷰는 합성 데이터입니다."
    error: RecommendErrorOut | None = None


# ── list confirm (S5-a) / report (S5-b) ──
class ConfirmIn(BaseModel):
    name: str
    planned_purchase_at: Optional[str] = None
    target_amount: Optional[int] = None


class ReportOut(BaseModel):
    list_id: str
    name: str
    items: list[dict]
    total: int
    buy_links: list[dict]
    price_watch: Optional[dict] = None


# ── reviews (A7) ──
class PartReviewIn(BaseModel):
    variant_id: str
    rating: int
    title: str
    body: str
    axis_scores: dict[str, Any] = Field(default_factory=dict)


class BuildReviewIn(BaseModel):
    build_version_id: str
    rating: int
    title: str
    body: str
    axis_scores: dict[str, Any] = Field(default_factory=dict)
