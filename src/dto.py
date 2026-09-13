"""파이프라인 단계 입출력 DTO (pydantic v2).

경계를 넘는 값(단계 간 전달 / LLM JSON / HTTP / DB 행)은 전부 여기에 정의한다.
경계를 넘지 않는 순수 내부 값은 그냥 dataclass/tuple 로 둔다.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Category = Literal["computer", "baby"]
Mode = Literal["build", "upgrade", "born", "prenatal"]
Verdict = Literal["Pass", "Fail", "Pending"]


# ── [1] 의도 분해 · 슬롯필링 ──────────────────────────────────────────────
class SlotFillResult(BaseModel):
    """LLM `fill_slots` tool 출력 스키마."""

    confirmed: dict[str, Any] = Field(default_factory=dict)
    assumed: dict[str, Any] = Field(default_factory=dict)
    assumed_reason: dict[str, str] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)


class Slots(BaseModel):
    """확정 + 가정을 병합한 최종 조건 세트."""

    category: Category
    mode: Mode
    objective_text: str
    values: dict[str, Any] = Field(default_factory=dict)       # confirmed > assumed > defaults
    assumed_keys: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)

    def can_recommend(self, required_inputs: list[str]) -> bool:
        return not (set(required_inputs) & set(self.missing))


# ── [2] 요구사양 빌드 ────────────────────────────────────────────────────
class RequirementSpec(BaseModel):
    list_id: str
    category: Category
    mode: Mode
    targets: dict[str, dict[str, Any]] = Field(default_factory=dict)   # slot -> 제약 floor
    link_rules: list[str] = Field(default_factory=list)               # computer
    chain_warnings: list[str] = Field(default_factory=list)           # upgrade
    budget: dict[str, Any] = Field(default_factory=dict)              # total, alloc, feasibility
    flags: list[str] = Field(default_factory=list)
    unresolved: list[dict[str, str]] = Field(default_factory=list)


# ── [3-0]~[3-B] 후보 ────────────────────────────────────────────────────
class Candidate(BaseModel):
    product_key: str
    slot: str
    name: str
    brand: str = ""
    price: int = 0
    specs: dict[str, Any] = Field(default_factory=dict)
    verdict: Verdict = "Pass"
    reasons: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    score: float = 0.0
    breakdown: dict[str, float] = Field(default_factory=dict)
    rank: int = 0


class HardFilterResult(BaseModel):
    slots: dict[str, list[Candidate]] = Field(default_factory=dict)          # Pass + 승격 Pending
    stats: dict[str, dict[str, int]] = Field(default_factory=dict)           # slot -> pool/pass/fail/pending


class RankResult(BaseModel):
    slots: dict[str, dict[str, Any]] = Field(default_factory=dict)           # slot -> ideal_tier/ranked/bottleneck_hint
    weights_used: dict[str, float] = Field(default_factory=dict)
    weight_adjustments: list[str] = Field(default_factory=list)


# ── [4] 세트 최적화 / 예산 배분 ─────────────────────────────────────────
class BuildItem(BaseModel):
    slot: str
    product_key: str
    name: str
    price: int
    perf_tier: float = 0.0
    score: float = 0.0
    rank_from_3b: int = 1


class BuildResult(BaseModel):
    list_id: str
    items: list[BuildItem] = Field(default_factory=list)
    totals: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)
    link_check: dict[str, str] = Field(default_factory=dict)
    balance: dict[str, Any] = Field(default_factory=dict)
    alternatives: dict[str, int] = Field(default_factory=dict)
    round: int = 1


class BasketLine(BaseModel):
    category: str
    sub_item: str
    product_key: str
    name: str
    price: int
    qty: int = 1
    score: float = 0.0
    timing: str = "now"


class BasketResult(BaseModel):
    list_id: str
    buy_now: list[BasketLine] = Field(default_factory=list)
    buy_later: list[BasketLine] = Field(default_factory=list)
    totals: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)
    adjustments: list[str] = Field(default_factory=list)


# ── [3-C] 적대적 검증 ───────────────────────────────────────────────────
class Issue(BaseModel):
    axis: str
    prosecutor: str = ""
    defender: str = ""
    tool_result: str = ""
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    judge: str = ""
    penalty: int = 0


class VerificationTarget(BaseModel):
    subject: str
    confidence: int = 0
    passed: bool = False
    rounds: int = 1
    issues: list[Issue] = Field(default_factory=list)
    gray_axes: list[str] = Field(default_factory=list)
    transcript: list[dict[str, Any]] = Field(default_factory=list)


class VerificationResult(BaseModel):
    list_id: str
    category: Category
    mode: Literal["set", "per_item"]
    targets: list[VerificationTarget] = Field(default_factory=list)


# ── [5] 설명 생성 ───────────────────────────────────────────────────────
class ExplanationItem(BaseModel):
    slot: str
    reason: str
    basis: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class Explanation(BaseModel):
    list_id: str
    headline: str = ""
    contribution: dict[str, int] = Field(default_factory=dict)   # 가격/성능/호환성
    items: list[ExplanationItem] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    review_line_by_slot: dict[str, str] = Field(default_factory=dict)


# (구 추천 결과 DTO는 §D-4-2 계약(RecommendResultOut, src/schemas.py)으로 대체되어 제거됨.
#  서비스 계층은 이제 dict를 직접 만들어 schemas.RecommendResultOut 경계를 통과시킨다.)


class BabyRequirement(BaseModel):
    """Stable baby requirement boundary for P1--P8."""
    id: str
    revision_id: str
    slot_key: str
    group_key: str | None = None
    required_qty: float = 1
    unit_code: str = "each"
    mandatory: bool = True
    timing: Literal["now", "soon", "later"] = "now"
    constraints: dict[str, Any] = Field(default_factory=dict)
    # v3 (develop `da79839` schema): planning.item never existed there and must not
    # reappear — ownership is represented directly from the revision's own
    # plan_condition rows, never a separate DB "item" id. Each entry:
    # {source_condition_id, label, qty, unit_code}; source_condition_id is a real
    # planning.plan_condition.id in the SAME revision (see
    # DEVELOP_DB_TRANSITION.md "Domain, requirements, ownership").
    owned: list[dict[str, Any]] = Field(default_factory=list)
    # Sum of owned[].qty capped at required_qty — always explicit, never a sentinel.
    fulfilled_qty: float = 0


class BabyCandidate(BaseModel):
    candidate_id: str
    requirement_id: str
    product_id: str
    variant_id: str | None = None
    product_key: str
    variant_key: str | None = None
    name: str
    slot_key: str
    price: int | None = None
    offer_observation_id: str | None = None
    observed_at: str | None = None
    stock_status: str = "unknown"
    pack_quantity: float = 1
    unit_code: str = "each"
    unit_qty: float = 1
    corpus: Literal["synthetic", "real"] = "real"
    market: str = "KR"
    language: str = "ko"
    facts: dict[str, Any] = Field(default_factory=dict)
    review_summary: dict[str, Any] | None = None
    score_breakdown: dict[str, float] = Field(default_factory=dict)


class CandidateCheck(BaseModel):
    requirement_id: str | None = None
    candidate_id: str
    eligibility: Literal["pass", "fail", "unknown"]
    verification: Literal["partial", "unknown", "verified"]
    coverage: Literal["partial", "full", "none", "error"]
    selection_allowed: bool
    issues: list[dict[str, Any]] = Field(default_factory=list)
    explanation_evidence: list[dict[str, Any]] = Field(default_factory=list)
    error_code: str | None = None


class ExplanationWithRefs(BaseModel):
    """P3 explain_baby_candidate() return — evidence used for the user-facing
    explanation, kept separate from CandidateCheck.explanation_evidence (verification's
    own cited evidence): the two are produced by different RAG queries/purposes and may
    legitimately cite different manual sections (CONTRACTS VE05)."""
    candidate_id: str
    status: Literal["ready", "pending", "failed"]
    text: str | None = None
    refs: list[dict[str, Any]] = Field(default_factory=list)
    error_code: str | None = None


class BasketItem(BaseModel):
    item_id: str
    requirement_id: str
    group_key: str | None = None
    candidate_id: str | None = None
    variant_id: str | None = None
    status: Literal["owned", "to_purchase", "purchased"]
    selected: bool = False
    qty: float = 1
    unit_code: str = "each"
    unit_qty: float = 1
    timing: Literal["now", "soon", "later"] = "now"
    unit_price: int | None = None
    offer_observation_id: str | None = None
    validation: dict[str, Any] = Field(default_factory=dict)


class BasketDecision(BaseModel):
    items: list[BasketItem] = Field(default_factory=list)
    totals: dict[str, Any] = Field(default_factory=dict)
    # P4: richer than a bare slot-key string — each mandatory-now requirement that
    # could not be fulfilled inside budget needs its own required_qty/cheapest
    # subtotal/shortfall so a caller doesn't have to recompute those from scratch
    # (CONTRACTS ALGORITHM step 5: "shortfall if computable ... unknown minimum
    # cost means unknown shortfall, not zero").
    missing_requirements: list[dict[str, Any]] = Field(default_factory=list)
    feasible: bool
    alternatives: dict[str, Any] = Field(default_factory=dict)


# ── P4 basket optimizer: ranking boundary between stage3b_rank and stage4_optimize ──
class ScoredCandidate(BaseModel):
    """One BabyCandidate scored for one requirement. Kept separate from Candidate
    (the PC [3-B] type) because baby scoring never fabricates a review fact and must
    carry selection_allowed/eligibility straight from P3's CandidateCheck instead of
    re-deriving them."""
    candidate_id: str
    requirement_id: str
    price: int | None = None
    unit_qty: float = 1
    score: float | None = None                      # None only if no configured axis was computable
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    selection_allowed: bool = False
    eligibility: Literal["pass", "fail", "unknown"] = "unknown"
    tie_break: tuple[int, str, str] = (0, "", "")    # (price, product_key, variant_key)


class RankedCandidates(BaseModel):
    profile_version: str
    weights: dict[str, float] = Field(default_factory=dict)
    by_requirement: dict[str, list[ScoredCandidate]] = Field(default_factory=dict)
    # structurally invalid candidates (bad price/units/identity) or ones missing a
    # CandidateCheck row entirely — tracked, never silently dropped (ALGORITHM step 1).
    excluded: list[dict[str, Any]] = Field(default_factory=list)


# ── 전체 결과 ───────────────────────────────────────────────────────────
class PipelineResult(BaseModel):
    scenario: str
    category: Category
    input_text: str
    slots: Optional[Slots] = None
    requirement: Optional[RequirementSpec] = None
    hard_filter: Optional[HardFilterResult] = None
    rank: Optional[RankResult] = None
    build: Optional[BuildResult] = None
    basket: Optional[BasketResult] = None
    verification: Optional[VerificationResult] = None
    explanation: Optional[Explanation] = None
    logs: list[str] = Field(default_factory=list)
