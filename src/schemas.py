"""API 요청/응답 모델 (pydantic).

엔진 내부 DTO(src/dto.py)와 분리한다 — API 계약은 프론트와 협의 후 확정(기획서 §18-1).
지금은 골격만. 필드는 화면흐름 명세 기준 최소.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── auth: 코드 로그인 (보류 — §G 재사용 예정) ──
class RequestCodeIn(BaseModel):
    email: str


class VerifyCodeIn(BaseModel):
    email: str
    code: str


class TokenOut(BaseModel):
    token: str


# ── auth: 이메일+비밀번호 (§A-4) ──
class SignupIn(BaseModel):
    email: str
    password: str
    display_name: str
    terms_agreed: bool
    privacy_agreed: bool
    marketing_agreed: bool = False


class LoginIn(BaseModel):
    email: str
    password: str
    remember: bool = False


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    marketing_agreed: bool
    created_at: datetime


class UserEnvelopeOut(BaseModel):
    """프론트 TF_AUTH가 `data.user`로 읽는다(frontend/js/api.js) — 사용자 응답은 항상 이 봉투로 감싼다."""

    user: UserOut


class ProfilePatchIn(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    marketing_agreed: Optional[bool] = None


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


class WithdrawIn(BaseModel):
    password: str


class EmailAvailabilityOut(BaseModel):
    available: bool


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
    mode: str | None = None
    revision_id: str | None = None
    lock_version: int | None = None
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


class ReviewSignalRatioOut(BaseModel):
    ratio: float
    median: float | None = None          # 대조군(비슷한 부품) 중앙값 — 막대그래프 기준선용


class ReviewSignalBurst7Out(BaseModel):
    count: int
    ratio: float
    launch_week: bool
    median: float | None = None


class ReviewSignalCountRatioOut(BaseModel):
    count: int
    ratio: float
    baseline: float | None = None        # 데모 상품 전체의 2개+ 비율 — 이 지표는 중앙값이 아니라 기준선과 비교한다


class ReviewSignalSharedReviewersOut(BaseModel):
    count: int
    linked_products: int
    median_count: int | None = None
    median_linked_products: int | None = None


class ReviewSignalsOut(BaseModel):
    """관계·행동 축 관측값을 문장이 아니라 숫자로 — 프론트가 막대그래프를 그리는 데 쓴다
    (docs/개발요청_리뷰클렌징_요약_구조화.md 요청 A). 개별 신호를 못 채우면 그 키만 None.
    median·baseline 은 "비슷한 부품은 보통 얼마인가" — 값만 있으면 유저가 크고 작음을 판단할 수 없다."""

    rating5_share: ReviewSignalRatioOut | None = None
    burst7: ReviewSignalBurst7Out | None = None
    suspect_2plus: ReviewSignalCountRatioOut | None = None
    shared_reviewers: ReviewSignalSharedReviewersOut | None = None


class ReviewPlainOut(BaseModel):
    """관측을 유저가 읽을 문장으로 (docs/리뷰관측_문장_초안.md). 숫자는 signals 와 같은 산출물, 말은 템플릿.

    3층: headline(한 줄) → points(사기 전에 살펴볼 점 — 중앙값을 넘어 뽑힌 것만) → details(나머지 지표) +
    sources(산출물 원문 — GET /reviews/summary 의 summaries 와 같은 문장, 검토자용) + verify_url.
    reason 이 있으면 관측이 없는 경우 — headline 이 그 사유 한 줄이고 points·details·sources 는 비어 있다.
    """

    headline: str
    points: list[str] = []
    details: list[str] = []
    sources: list[str] = []
    verify_url: str | None = None
    reason: str | None = None            # below_threshold | out_of_period | no_match | unmapped | unavailable


class ReviewBriefOut(BaseModel):
    total_count: int
    # 정제 전/후 비교는 판정기가 없어 못 낸다(docs/decisions/0001) — 항상 null.
    excluded_ratio: float | None = None
    rating_refined: float | None = None
    signals: ReviewSignalsOut | None = None
    cleansing_summary: TextStatusOut | None = None
    plain: ReviewPlainOut | None = None


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
    # P3 full-catalog verification (2026-09-14): true whenever this result's baby
    # candidates were only checked against synthetic_demo-scope evidence — never a
    # real product safety certification. False/omitted once a production-scope
    # result exists (docs/agent-tasks/baby/P3_full_catalog_verification_execution.md).
    synthetic_verification_only: bool | None = None
    synthetic_notice: str | None = None


class ItemPatchIn(BaseModel):
    selected: Optional[bool] = None
    qty: Optional[int] = Field(default=None, ge=1, le=99)
    timing: Optional[Literal["now", "soon", "later"]] = None


class AlternativeOut(BaseModel):
    candidate_id: str
    label: str
    current: bool = False
    product: ProductOut
    price: int
    price_delta: int
    review: ReviewBriefOut | None = None


class AlternativesOut(BaseModel):
    items: list[AlternativeOut] = Field(default_factory=list)


class SwapIn(BaseModel):
    candidate_id: str


class ResultMessageIn(BaseModel):
    text: str = Field(max_length=300)


class SpecFileIn(BaseModel):
    file_name: str
    content: str = Field(max_length=1_000_000)


class RecommendErrorOut(BaseModel):
    code: str
    message: str


class RecommendResultOut(BaseModel):
    """저장된 추천 실행 결과의 공개 API 계약 (docs/frontend_외부수정요청.md §D-4-2)."""

    list_id: str
    revision_id: str | None = None
    lock_version: int | None = None
    run_id: str
    status: str                      # running | done | failed
    content_language: Literal["ko-KR", "en-US"] = "ko-KR"
    progress: list[ProgressStepOut] = Field(default_factory=list)
    category: str
    conditions_summary: str = ""
    budget_max: int | None = None
    items: list[ItemOut] = Field(default_factory=list)
    totals: TotalsOut | None = None
    verification: VerificationOut = Field(default_factory=lambda: VerificationOut(status="pending"))
    explanation: ExplanationOut = Field(default_factory=lambda: ExplanationOut(status="pending"))
    feasible: bool = True
    missing_requirements: list[dict] = Field(default_factory=list)
    reasoning_log: list[dict] = Field(default_factory=list)
    data_notice: str = "상품·가격·리뷰는 합성 데이터입니다."
    # 04 리스트 확정 "메모" 초기값 — 조건·구성·직접 바꾼 것·확인 필요 사항을 코드가 정리한 문장 (done 일 때만)
    memo_suggestion: str = ""
    error: RecommendErrorOut | None = None


class ResultMessageOut(BaseModel):
    reply: str
    result: RecommendResultOut


# ── 사이드바 목록 · 확정(S5-a) · 리포트(S5-b) · 가격 알림 (§D-4-3) ──
class ListSummaryOut(BaseModel):
    list_id: str
    name: str
    category: Optional[str] = None
    stage: Literal["category", "conditions", "results", "report"]
    updated_at: datetime


class ListsOut(BaseModel):
    items: list[ListSummaryOut] = Field(default_factory=list)


class ListRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class ConfirmIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    planned_purchase_at: Optional[str] = None
    target_amount: Optional[int] = Field(default=None, ge=0)
    memo: str = Field(default="", max_length=1000)


class ReportProductOut(BaseModel):
    product_key: str
    name: str
    image_url: str | None = None
    purchase_url: str | None = None


class ReportItemOut(BaseModel):
    slot: str
    slot_label: str
    product: ReportProductOut
    price: int
    qty: int = 1
    timing: str = "now"
    review: ReviewBriefOut | None = None
    evidence_text: str | None = None


class PriceWatchOut(BaseModel):
    enabled: bool
    target_amount: int | None = None
    status: Literal["waiting", "tracking", "reached"] = "waiting"
    latest_total: int | None = None
    observed_at: str | None = None


class ReportOut(BaseModel):
    list_id: str
    name: str
    category: str
    owner_display_name: str
    planned_purchase_at: str | None = None
    target_amount: int | None = None
    memo: str = ""
    total: int
    confirmed_at: str
    items: list[ReportItemOut] = Field(default_factory=list)
    price_watch: PriceWatchOut
    care_guide: TextStatusOut = Field(default_factory=lambda: TextStatusOut(status="pending"))
    data_notice: str = "상품·가격·리뷰는 합성 데이터입니다."


class AlertIn(BaseModel):
    enabled: bool
    target_amount: Optional[int] = None


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

    P8: `excluded_count`·`excluded_ratio`·`rating_refined`·`distribution_refined`는
    더 이상 항상 null이 아니다 — evidence.review_aggregate에 검수 승인된 파일 기반
    분석(review_service._db_backed_analysis)이 있으면 실제 값을 낸다. 판정기가 없는
    관계·행동 축 관측 경로(PC 부품)는 그 분석이 없으므로 계속 null만 낸다 — 필드
    타입만 넓혔을 뿐 기존 PC 경로의 동작은 바뀌지 않는다.
    """
    product_key: str
    total_count: int = 0
    excluded_count: Optional[int] = None
    excluded_ratio: Optional[float] = None
    rating_raw: Optional[float] = None
    rating_refined: Optional[float] = None
    distribution_raw: dict[str, float] = {}
    distribution_refined: dict[str, float] = {}
    summaries: list[dict[str, Any]] = []
    data_notice: str
    analysis_version: Optional[str] = None
    status: str = "unavailable"          # unavailable | ready — DB 분석 유무
    # ── 계약 밖 추가 ──
    product_name: Optional[str] = None
    product_manipulation_risk: ProductRiskOut
    synthetic_demo: Optional[SyntheticDemoOut] = None
