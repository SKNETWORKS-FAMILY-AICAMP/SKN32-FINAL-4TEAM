"""리뷰 서비스 — A7 부품 리뷰 / 전체 PC 리뷰 작성 · 게시 · 개봉/구매 인증.

부품 리뷰 = product/variant 대상, 자기신고. 전체 PC 리뷰 = pc_build_version/component 고정 +
assembled_self_reported 확인 후 게시(C11). 외부 리뷰 원문 미저장.
"""
from __future__ import annotations

from uuid import UUID

from src.config import REVIEW_SUMMARIES_DEMO
from src.errors import NotFound
from src.repo.review_repo import (OBS_LABEL, SUSPECT_SOURCE, ReviewSummaryDemoFile,
                                 default_risk_store, default_suspect_counts)
from src.schemas import ProductRiskOut, ReviewSummaryOut, ReviewTelemetry, SyntheticDemoOut

TELEMETRY_KEY = "telemetry"

# summaries[].source — 이 문장이 리뷰 발췌가 아니라 상품 단위 집계 사실이라는 표시.
# 계약의 예시가 "합성 리뷰 요약" 을 쓰는 것과 같은 자리다.
OBSERVATION_SOURCE = "관계·행동 축 관측 (리뷰 본문 아님)"

_demo_file: ReviewSummaryDemoFile | None = None


def _stores():
    """파일 기반 산출물 — DB 연결 전까지의 자리. 산출 JSON 이 없으면 관측 없이 데모 블록만."""
    global _demo_file
    if _demo_file is None:
        _demo_file = ReviewSummaryDemoFile(REVIEW_SUMMARIES_DEMO)
    return default_risk_store(), _demo_file


def candidate_keys(product_key: str) -> list[str]:
    """받은 키를 그대로, 그리고 엔진이 쓰는 슬러그 모양으로도 찾아본다.

    저장 경로에서 `product_key` 가 가리키는 값이 갈아탄다 — [3-B] 후보는 슬러그
    (`asus-tuf-gaming-b650-plus-wifi`)를 쓰는데, `GET /session/{id}/result` 는
    `catalog.product.model`(제품명 원문 `ASUS TUF GAMING B650-PLUS WIFI`)을 같은 이름으로
    내보낸다. 화면은 그 값을 그대로 이 엔드포인트에 넘기므로 전부 404 가 됐다.

    근본 원인은 후보 수집·결과 조립 쪽(슬러그를 DB 에 남기지 않는다)이고 이 모듈의 자리가
    아니다. 그래서 여기서는 **받는 쪽에서 흡수만** 한다 — 저쪽이 고쳐지면 첫 후보가 바로 맞고
    이 함수는 아무 일도 하지 않는다. 변환 규칙이 두 곳에 생기는 것이 대가다.
    """
    keys = [product_key]
    slug = product_key.strip().lower().replace(" ", "-")
    if slug and slug not in keys:
        keys.append(slug)
    return keys


def get_summary(product_key: str) -> ReviewSummaryOut:
    """S5 리뷰 상세. 실측(관계·행동 축 관측)과 합성 데모 블록을 분리해 낸다.

    - 관측은 상품 단위이고 점수가 아니다. 개별 리뷰의 진위가 아니다
    - cleaned_rating · cleanse_ratio 는 항상 null — 판정기가 없다(docs/decisions/0001)
    - 항목별 평가·요약 3건은 지금 합성 데모뿐이라 `synthetic_demo` 에 표지와 함께 둔다
    """
    store, demo = _stores()
    key, facts, d = product_key, None, None
    for cand in candidate_keys(product_key):
        facts = store.get(cand) if store else None
        d = demo.get(cand) if demo else None
        if facts is not None or d is not None:
            key = cand
            break
    if facts is None and d is None:
        raise NotFound(f"리뷰 요약 없음: {product_key}", field="product_key")

    if facts is not None:
        auth = store.get_review_authenticity(key)
        risk = auth["product_manipulation_risk"]
        ref = risk.get("product_ref")
        risk_out = ProductRiskOut(
            evidence=risk["evidence"], reliable_range=risk["reliable_range"],
            controls=risk.get("controls", {}), control_scope=store.meta.get("control_scope"),
            product_ref=ref, verify_url=f"https://www.amazon.com/dp/{ref}" if ref else None)
        orig, total, note = auth["orig_rating"], auth["total_reviews"], auth["confidence_note"]
        # 관측 문장을 계약의 summaries 자리에 낸다. 화면에 문장을 실을 칸이 여기뿐이다.
        # source 로 출처를 밝혀 리뷰 발췌로 읽히지 않게 한다 — 이건 본문이 아니라 집계 사실이다.
        # (오버레이에 관측 사실 전용 칸이 생기면 그쪽으로 옮긴다)
        summaries = [{"text": t, "source": OBSERVATION_SOURCE, "observed_at": None}
                     for t in risk["evidence"]]
        # 규칙 기반 의심 건수 — 판정이 아니라는 표시(SUSPECT_SOURCE)를 문장과 함께 붙인다
        sus = default_suspect_counts()
        line = sus.sentence(key) if sus else None
        if line:
            summaries.append({"text": line, "source": SUSPECT_SOURCE, "observed_at": None})
    else:
        risk_out = ProductRiskOut(evidence=[], reliable_range=None)
        orig, total, summaries = None, 0, []
        note = ("관측 없음 — 이 상품은 관계·행동 축 산출물에 없다(리뷰 수 문턱 미만이거나 데이터 기간 밖). "
                "정제 평점·제외 비율은 산출하지 않는다.")

    synthetic = None
    if d is not None:
        synthetic = SyntheticDemoOut(
            note=d.get("cleaned_rating_note", "합성 데모값"),
            cleaned_rating=d.get("cleaned_rating"), cleanse_ratio=d.get("cleanse_ratio"),
            removed_count=d.get("removed_count"), rating_dist=d.get("rating_dist", {}),
            axis_scores=d.get("axis_scores", {}), top_summaries=d.get("top_summaries", []),
            sources=d.get("sources", []), collected_at=d.get("collected_at"))

    return ReviewSummaryOut(
        product_key=key, product_name=d.get("product_name") if d else None,
        total_count=total, rating_raw=orig, summaries=summaries, data_notice=note,
        product_manipulation_risk=risk_out, synthetic_demo=synthetic)


def usage_context_with_telemetry(usage_context: dict | None, telemetry: ReviewTelemetry | None) -> dict:
    """`review_revision.usage_context` 에 폼 계측값을 `telemetry` 키로 넣는다.

    없으면 키를 만들지 않는다 — 빈 dict 나 0 으로 채우면 "붙여넣기 0회 = 직접 씀" 으로 읽히는데
    그건 이 신호가 말하지 않는 것이다. 있을 때만, 정수만 들어간다(ReviewTelemetry 가 거른다).
    """
    ctx = dict(usage_context or {})
    if telemetry is not None:
        ctx[TELEMETRY_KEY] = telemetry.model_dump()
    return ctx


def write_part_review(user_id: UUID, variant_id: UUID, *, rating: int, title: str,
                      body: str, axis_scores: dict, telemetry: ReviewTelemetry | None = None) -> dict:
    """usage_context = usage_context_with_telemetry(…, telemetry) 로 add_revision 에 넘긴다."""
    raise NotImplementedError


def write_build_review(user_id: UUID, build_version_id: UUID, *, rating: int, title: str,
                       body: str, axis_scores: dict, telemetry: ReviewTelemetry | None = None) -> dict:
    """build.owner == author, build_version published, usage_status assembled_self_reported 확인.
    usage_context 는 write_part_review 와 같은 규칙."""
    raise NotImplementedError


def publish(review_id: UUID, user_id: UUID) -> None:
    raise NotImplementedError


def list_pending_for_user(user_id: UUID) -> dict:
    """A7: 작성해야 할 리뷰 / 개봉 확인 / 내가 쓴 리뷰."""
    raise NotImplementedError


# ── [5] 리뷰 관측을 저장 경로로 나르기 ──────────────────────────────────────
# [3-B] 가 랭킹에 반영하고 [5] 가 문장으로 만든 관측 사실은, DB 경로
# (POST /session/{id}/recommend → engine.recommendation_run)에서 버려지고 있었다.
# stage5 의 review_line_by_slot·caveats 를 아무도 읽지 않아서, 감점은 되는데
# "왜" 가 화면에 안 갔다 — 점수 대신 확인·반박 가능한 문장을 낸다는 설계의 정반대다.
#
# 자리를 둘 다 **쓰지 않는** 이유를 남겨 둔다:
#   · `ItemOut.review`(ReviewBriefOut) — 필드가 excluded_ratio·rating_refined 다.
#     정제 후 평점을 판정기 없이 내지 않는다는 결정(docs/decisions/0001)과 충돌한다.
#     "제외 0건" 으로 채우면 화면이 "조작 제외 전후 평점" 으로 그리므로, 클렌징이
#     돌아서 아무것도 못 찾은 것처럼 읽힌다. 우리는 탐지기를 돌리지 않았다
#   · `ItemOut.checks`("구매 전 확인") — [3-C] 스펙 검증 문장의 자리다. 상품 단위
#     리뷰 관측을 섞으면 나중에 [3-C] 가 채울 때 서로 덮는다
# 그래서 이미 자유 형식인 reasoning_log(추천 과정 기록)와 explanation_text 에 싣는다.

REVIEW_TRACE_STEP = "리뷰 관측"


def review_trace_steps(review_line_by_slot: dict[str, str],
                       evidence_by_slot: dict[str, list[dict]] | None = None) -> list[dict]:
    """[5] 의 리뷰 관측을 reasoning_log 단계들로. 관측이 없으면 빈 목록.

    첫 단계는 요약(N/M 슬롯), 이어서 **관측 문장이 있는 슬롯마다 한 단계**다.
    "리뷰 449건 중 15건(3.3%)이 7일 안에 몰림 — 전체 상품 중앙값 5.5%" 처럼
    값과 대조군 중앙값을 그 자리에 풀어 쓴 문장이고, 점수가 아니다. 검토자가
    확인·반박할 수 있어야 하므로 원 상품 주소(verify_url)도 같이 낸다.

    슬롯마다 나누는 이유: 화면이 detail 을 한 단락으로 그린다. 세 슬롯의 문장
    아홉 개를 한 단락에 넣으면 읽을 수 없다.

    관측이 하나도 없으면 단계를 만들지 않는다 — "리뷰를 봤지만 깨끗했다" 와
    "볼 리뷰가 없었다" 는 다른 말이고, 뒤쪽을 앞쪽으로 보이게 하면 안 된다.
    """
    observed = {slot: line for slot, line in (review_line_by_slot or {}).items()
                if line and not line.startswith("리뷰 관측 없음")}
    if not observed:
        return []
    steps = [{
        "step": REVIEW_TRACE_STEP,
        "title": f"{REVIEW_TRACE_STEP} {len(observed)}/{len(review_line_by_slot)} 슬롯",
        "detail": " · ".join(f"{slot} {line}" for slot, line in observed.items()),
    }]
    for slot in observed:
        facts = [e for e in (evidence_by_slot or {}).get(slot, []) if e.get("text")]
        if not facts:
            continue
        detail = " · ".join(e["text"] for e in facts)
        verify = next((e.get("verify_url") for e in facts if e.get("verify_url")), None)
        if verify:
            detail += f" — 확인: {verify}"
        steps.append({
            "step": f"{REVIEW_TRACE_STEP} · {slot}",
            "title": f"{slot} 관측 사실 {len(facts)}건 (점수 아님)",
            "detail": detail,
        })
    return steps


def review_demotion_step(demoted_by_slot: dict[str, list[dict]] | None) -> dict | None:
    """리뷰축이 **순위를 낮춘 후보**를 reasoning_log 한 단계로. 없으면 None.

    추천된 8개는 대개 "특이 없음" 이다 — 걸린 후보가 감점을 받아 밀려나기 때문이다. 그래서
    축이 실제로 한 일(덜 보여준 것)이 화면에 하나도 안 나온다. 랭킹은 알고 있는데 안 말한다.

    낮춘 것은 **제외가 아니다.** 후보 목록에 그대로 남아 있고 순위만 내려갔다 — 되돌릴 수 있는
    자리라 검증 없이 쓴다는 것이 이 축을 랭킹에만 쓰는 근거다(`docs/decisions/0001`).
    그래서 문장도 "제외" 가 아니라 "순위를 낮췄다" 로 쓴다.

    `demoted_by_slot`: {슬롯: [{"name": 상품명, "over": [(지표, 값, 중앙값), ...]}, ...]}
    """
    rows = [(slot, d) for slot, ds in (demoted_by_slot or {}).items() for d in ds if d.get("over")]
    if not rows:
        return None
    parts = []
    for slot, d in rows:
        facts = " · ".join(f"{OBS_LABEL.get(k, k)} {100 * v:.1f}% (부류 중앙값 {100 * m:.1f}%)"
                           for k, v, m in d["over"])
        parts.append(f"{slot} {d.get('name', '?')} — {facts}")
    return {
        "step": f"{REVIEW_TRACE_STEP} · 순위 조정",
        "title": f"관측 때문에 순위를 낮춘 후보 {len(rows)}개 (제외 아님)",
        "detail": " · ".join(parts) + " — 후보 목록에는 남아 있고 순위만 내렸습니다",
    }


def explanation_text_with_caveats(item_reasons: list[str], caveats: list[str]) -> str:
    """explanation_text = 추천 이유 목록 + 확인이 필요한 것. caveats 가 비면 이유만."""
    body = "\n".join(f"- {r}" for r in item_reasons)
    if not caveats:
        return body
    return body + "\n\n확인이 필요한 것:\n" + "\n".join(f"- {c}" for c in caveats)
