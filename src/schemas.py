"""API 요청/응답 모델 (pydantic).

엔진 내부 DTO(src/dto.py)와 분리한다 — API 계약은 프론트와 협의 후 확정(기획서 §18-1).
지금은 골격만. 필드는 화면흐름 명세 기준 최소.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


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
class ReviewTelemetry(BaseModel):
    """리뷰 작성 폼의 계측값 — 횟수와 시간뿐, 타이핑 내용은 받지 않는다.

    리뷰 진위 축 중 유일하게 소급 수집이 불가능한 것이라 폼이 생기는 지금 넣는다.
    `review_revision.usage_context.telemetry` 로 저장된다 (테이블 변경 없음).
    양성 신호로만 쓴다 — "붙여넣기 없음" 은 무죄 증거가 아니다 (보고 타이핑하는 우회가 너무 쉽다).
    정수 외의 값·모르는 키는 거부한다: 본문이나 키 입력 내용이 이 경로로 들어오면 안 된다.
    """
    model_config = ConfigDict(extra="forbid")

    paste_count: int = Field(0, ge=0, description="붙여넣기 이벤트 수")
    paste_chars: int = Field(0, ge=0, description="붙여넣은 글자 수 합계 (내용 아님)")
    typing_ms: int = Field(0, ge=0, description="키 입력이 있었던 시간 합계 (ms)")
    edit_count: int = Field(0, ge=0, description="삭제·수정 이벤트 수")
    compose_ms: int = Field(0, ge=0, description="폼을 연 뒤 제출까지 (ms)")


class PartReviewIn(BaseModel):
    variant_id: str
    rating: int
    title: str
    body: str
    axis_scores: dict[str, Any] = Field(default_factory=dict)
    telemetry: Optional[ReviewTelemetry] = None


class BuildReviewIn(BaseModel):
    build_version_id: str
    rating: int
    title: str
    body: str
    axis_scores: dict[str, Any] = Field(default_factory=dict)
    telemetry: Optional[ReviewTelemetry] = None


class ProductRiskOut(BaseModel):
    """상품 단위 관측 사실. 점수 없음 — 검토자가 확인·반박할 수 있는 문장과 대조군 중앙값."""
    score: None = None
    evidence: list[str] = []
    reliable_range: Optional[bool] = None
    controls: dict[str, float] = {}
    control_scope: Optional[str] = None
    product_ref: Optional[str] = None            # 관측이 붙은 외부 상품 식별자 (예: ASIN)
    verify_url: Optional[str] = None


class SyntheticDemoOut(BaseModel):
    """합성 데모값 블록 — 화면은 반드시 '합성 데모값' 표지와 함께 보여준다. 실사용자 노출 금지."""
    is_synthetic: Literal[True] = True
    note: str
    cleaned_rating: Optional[float] = None
    cleanse_ratio: Optional[float] = None
    removed_count: Optional[int] = None
    rating_dist: dict[str, Any] = {}
    axis_scores: dict[str, Any] = {}
    top_summaries: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    collected_at: Optional[str] = None


class ReviewSummaryOut(BaseModel):
    """S5 리뷰 상세 — 프론트 계약(`docs/frontend_외부수정요청.md` §D-4-2 `ReviewSummary`) 의 이름을 따른다.

    **못 내는 값도 이름을 바꾸지 않고 null 로 둔다.** 전에는 이름을 달리 지었는데(`total_reviews`·
    `orig_rating`), 화면이 계약 이름을 읽으므로 실제로 낼 수 있는 리뷰 건수까지 **"리뷰 0건"** 으로
    나갔다. 없는 값을 0 으로 단정하는 것이 빈 칸보다 나쁘다.

    낼 수 없는 것과 이유:

    - `excluded_count` · `excluded_ratio` · `rating_refined` — 판정기가 없다(`docs/decisions/0001`).
      관계·행동 축은 상품 단위 신호라 **개별 리뷰를 하나도 빼지 않는다.** 몰림 15건을 `excluded_count`
      에 넣으면 화면이 "449건 중 15건 제외" 로 그려서 우리가 그 15건을 조작으로 판정하고 뺐다는
      말이 된다. 몰림은 출시·이벤트·인플루언서 언급·재입고로도 생긴다(몰림 2배 초과 상품 915개 중
      109개(11.9%)가 출시 첫 주였고, 그 밖의 설명은 이 데이터로 가릴 수 없다)
    - `distribution_refined` — "후" 가 없으므로 없다
    - `distribution_raw` — 산출물에 5점·1점 비율만 있고 4·3·2 가 없다. 부분만 내면 화면이 나머지를
      0% 로 그려서 없는 분포를 단정한다

    실측과 합성은 섞지 않는다 — 합성값은 `synthetic_demo` 안에만, `is_synthetic` 표지와 함께.
    """
    product_key: str
    total_count: int = 0
    excluded_count: None = None
    excluded_ratio: None = None
    rating_raw: Optional[float] = None
    rating_refined: None = None
    distribution_raw: dict[str, float] = {}
    distribution_refined: dict[str, float] = {}
    summaries: list[dict[str, Any]] = []
    data_notice: str
    # ── 계약 밖 추가 ──
    product_name: Optional[str] = None
    product_manipulation_risk: ProductRiskOut
    synthetic_demo: Optional[SyntheticDemoOut] = None
