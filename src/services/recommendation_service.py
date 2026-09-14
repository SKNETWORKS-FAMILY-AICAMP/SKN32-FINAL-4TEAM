"""추천 서비스 — [추천 실행] → 엔진 파이프라인 → 결과 영속화.

계약: docs/frontend_외부수정요청.md §D-4-2 (202 접수 + GET /result 폴링).
start_recommendation() 이 요청 트랜잭션 안에서 run 행만 만들고 즉시 반환하고,
execute_recommendation() 이 백그라운드 태스크(자체 커넥션)에서 엔진을 실제로 돌려 저장한다.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from src.categories import load_category
from src.dto import PipelineResult, Slots
from src.errors import Conflict, NotFound, ValidationFailed
from src.pipeline import run_pipeline as _run_scenario

log = logging.getLogger(__name__)


def run_from_scenario(scenario_name: str) -> PipelineResult:
    """개발용: 시나리오 파일로 파이프라인 1회 (DB 미사용)."""
    return _run_scenario(scenario_name, on_log=lambda _m: None)


def _slots_from_conditions(category: str, cat_def: dict, values: dict) -> Slots:
    defaults = cat_def.get("defaults") or {}
    assumed = {k: v for k, v in defaults.items() if values.get(k) in (None, [], "")}
    full = {**assumed, **values}
    return Slots(
        category=category, mode=full.get("mode", (cat_def.get("modes") or ["build"])[0]),
        objective_text="(대화로 수집됨)", values=full,
        assumed_keys=list(assumed.keys()), missing=[],
    )


def start_recommendation(conn, revision_id: UUID, *, strategy: str = "default") -> dict:
    """POST /recommend 가 호출 — run 행을 만들고 즉시 접수 응답만 반환한다 (202).

    실제 엔진 실행은 여기서 하지 않는다 — 호출 쪽(라우터)이 execute_recommendation을
    BackgroundTasks 로 별도 커넥션에서 돌린다.
    """
    from src.repo.engine_repo import EngineRepo
    from src.repo.plan_repo import PlanRepo

    prepo, erepo = PlanRepo(conn), EngineRepo(conn)
    revision = prepo.get_revision(revision_id)
    if revision is None:
        raise ValidationFailed("계획 버전을 찾을 수 없습니다.", field="list_id")
    full = prepo.load_full(revision_id)
    values = {row["condition_key"]: row["value"].get("value") for row in full["conditions"]}
    category = values.get("category")
    if category is None:
        raise Conflict("카테고리를 먼저 선택하세요.", code="category_required")
    if category != "computer":
        raise NotImplementedError("start_recommendation: 유아 경로는 run_baby_db_pipeline으로 별도 구현됨")

    cat_def = load_category(category)
    from src.services import session_service
    missing = session_service.compute_missing(cat_def, values)
    if missing:
        raise ValidationFailed(f"필수 조건이 아직 안 채워졌습니다: {missing}", field="conditions", code="conditions_incomplete")
    if erepo.has_running_run(revision_id):
        raise Conflict("이미 추천을 실행하는 중입니다.", code="run_in_progress")

    run_id = erepo.start_run(
        revision_id, revision["domain_version_id"],
        input_snapshot={"values": values, "strategy": strategy},
        input_hash=hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest(),
        draft_lock_version=revision["lock_version"],
        engine_versions={"pipeline": "computer-v1"},
    )
    return {"run_id": str(run_id), "status": "running"}


def execute_recommendation(revision_id: UUID, run_id: UUID) -> None:
    """백그라운드 태스크 — 엔진 [2]~[5] 실행 + 저장 + run 종료. 자체 커넥션을 연다."""
    from src.db import get_conn
    from src.engine import stage2_requirement, stage3a_hardfilter, stage3b_rank, stage3c_verify, stage4_optimize, stage5_explain
    from src.repo.catalog_repo import load_candidates_by_slot
    from src.repo.engine_repo import EngineRepo
    from src.repo.plan_repo import PlanRepo
    from src.repo.product_repo import ProductRepo
    from src.repo.review_repo import is_obs_flag, parse_obs_flag
    from src.services import review_service

    noop = lambda _m: None  # noqa: E731

    # get_conn() 은 with 블록 전체를 트랜잭션 하나로 묶어 블록이 끝날 때 한 번만 커밋한다.
    # 그래서 [2]~[4]+검증과 [5]를 같은 with 블록에 두면 complete_run을 앞당겨 불러도
    # [5]가 끝나기 전엔 아무것도 커밋되지 않아 폴링 중인 GET /result가 여전히 못 본다.
    # 두 블록(=두 트랜잭션)으로 쪼개야 부품표가 [5] 완료 전에 실제로 보인다.
    try:
        with get_conn() as conn:
            prepo, erepo, prodrepo = PlanRepo(conn), EngineRepo(conn), ProductRepo(conn)
            full = prepo.load_full(revision_id)
            values = {row["condition_key"]: row["value"].get("value") for row in full["conditions"]}
            category = values["category"]
            cat_def = load_category(category)
            slots = _slots_from_conditions(category, cat_def, values)

            spec = stage2_requirement.run(slots, cat_def, noop)
            spec.list_id = str(revision_id)

            req_id_by_slot = {}
            for slot in spec.targets:
                node_id = prepo.ensure_node(revision_id, slot, slot)
                req_id_by_slot[slot] = prepo.ensure_requirement(revision_id, node_id, spec.targets[slot])

            by_slot = load_candidates_by_slot()
            hf = stage3a_hardfilter.run(spec, by_slot, noop)
            rank = stage3b_rank.run(hf, spec, slots, noop)
            build = stage4_optimize.run(rank, spec, noop)
            build.list_id = str(revision_id)
            verification = stage3c_verify.verify_build(build, category, noop)

            # 부품·가격·검증은 여기서 이미 확정됐다. [5] 설명 문장(LLM)은 아직 안 돌았으므로
            # reason=None 으로 저장한다 — add_candidate가 자동으로 reason_status='pending' 처리.
            candidate_id_by_slot: dict[str, UUID] = {}
            for item in build.items:
                variant_id = prodrepo.variant_id_by_model(item.name)
                if variant_id is None:
                    continue  # 카탈로그 미적재 — 이 슬롯은 저장 못 함, 나머지는 계속 진행
                offer_observation_id = prodrepo.offer_observation_id_by_variant(variant_id)
                candidate_id_by_slot[item.slot] = erepo.add_candidate(
                    run_id, req_id_by_slot[item.slot], variant_id, result="selected",
                    score=item.score, score_method_version="v1", reason=None,
                    offer_observation_id=offer_observation_id,
                )

            for issue in verification.targets[0].issues if verification.targets else []:
                erepo.add_validation(
                    run_id, rule_key=issue.axis, rule_version="v1", executor_version="v1",
                    status="fail" if issue.penalty >= 15 else "unknown",
                    severity="warning" if issue.penalty >= 15 else "info",
                    measured_values={"penalty": issue.penalty, "confidence": verification.targets[0].confidence},
                    threshold={}, message=issue.text or issue.judge or issue.axis,
                    checked_at=datetime.now(timezone.utc),
                )

            erepo.complete_run(run_id)
        # ↑ with 블록이 끝나며 여기서 커밋된다 — 부품·가격·검증이 done으로 확정.
    except Exception:  # noqa: BLE001 — 실패해도 running으로 영원히 남지 않게 별도 커넥션으로 failed 처리
        with get_conn() as fail_conn:
            fail_conn.execute(
                "UPDATE engine.recommendation_run SET status='failed', completed_at=now(), updated_at=now() "
                "WHERE id=%s AND status='running'",
                (run_id,),
            )
        raise

    # [5] 설명 문장(LLM 호출) — 별도 트랜잭션. 실패해도 위에서 이미 커밋한 부품·가격·검증에는
    # 영향이 없다. run.status는 건드리지 않고 문장 쪽 상태(reason_status/explanation_status)만 옮긴다.
    try:
        with get_conn() as conn:
            erepo = EngineRepo(conn)
            # rank 를 넘겨야 [3-B] 가 후보에 남긴 리뷰 관측 플래그를 [5] 가 읽는다.
            # 빼면 모든 슬롯이 "관측 없음" 이 되고, 감점만 남고 근거가 사라진다 (기본값이 None 이라 조용히).
            explanation = stage5_explain.run(build, verification, noop, rank=rank)

            for it in explanation.items:
                candidate_id = candidate_id_by_slot.get(it.slot)
                if candidate_id is not None and it.reason is not None:
                    erepo.update_candidate_reason(candidate_id, it.reason)

            # [5] 의 리뷰 관측(review_line_by_slot)·확인 필요(caveats)를 저장 경로에 싣는다.
            # 여기서 안 실으면 [3-B] 감점은 되는데 "왜" 가 화면에 안 간다 (review_service 주석 참고).
            trace = [{"step": s, "title": s, "detail": d} for s, d in [
                ("조건 정리", f"카테고리 {category}, 예산 {values.get('budget_max'):,}원" if values.get("budget_max") else "조건 정리"),
                ("후보 수집", f"세트 {len(build.items)}개 부품"),
                ("설명 생성", explanation.headline),
            ]]
            # 관측 문장(7일 몰림 · 공유 리뷰어 · 5점 비율)은 슬롯별 evidence 에 있다.
            # 그것까지 실어야 검토자가 확인·반박할 수 있다 — 요약만으로는 못 한다.
            evidence_by_slot = {it.slot: it.evidence for it in explanation.items if it.evidence}
            for step in review_service.review_trace_steps(explanation.review_line_by_slot, evidence_by_slot):
                trace.insert(-1, step)

            # 리뷰축이 순위를 낮춘 후보 — 추천된 것들은 대개 "특이 없음" 이라(걸린 것이 밀려나므로)
            # 축이 실제로 한 일이 화면에 안 나온다. rank 는 알고 있으니 꺼내 싣는다.
            demoted: dict[str, list[dict]] = {}
            for slot, info in rank.slots.items():
                for c in info.get("ranked", []):
                    over = [pair for pair in
                            (parse_obs_flag(f) for f in c.get("flags", []) if is_obs_flag(f))
                            if pair is not None]
                    if over:
                        demoted.setdefault(slot, []).append({"name": c.get("name", "?"), "over": over})
            demotion = review_service.review_demotion_step(demoted)
            if demotion is not None:
                trace.insert(-1, demotion)

            erepo.set_explanation(
                run_id, headline=explanation.headline,
                text=review_service.explanation_text_with_caveats(
                    [it.reason for it in explanation.items], explanation.caveats),
                reasoning_log=trace,
            )
    except Exception:  # noqa: BLE001 — [5] 실패는 문장만 failed, 부품표는 이미 done인 채로 둔다
        with get_conn() as fail_conn:
            fail_erepo = EngineRepo(fail_conn)
            for candidate_id in candidate_id_by_slot.values():
                fail_erepo.fail_candidate_reason(candidate_id)
            fail_erepo.fail_explanation(run_id)


def verify_and_explain_baby_candidate(*, rag_service, engine_repo, run_id, candidate: dict, slots: dict) -> dict:
    """후보 하나의 설명서 검증/설명과 채택 evidence 연결.

    검색 실패는 unknown이며 pass로 승격하지 않는다. 직렬화할 인용은 resolve_evidence
    재검사를 통과한 것만 반환한다.
    """
    from src.engine.stage3c_verify import verify_baby_manual
    from src.engine.stage5_explain import explain_manual
    from src.rag.contracts import SearchRequest
    product_key, variant_key = candidate.get("product_key"), candidate.get("variant_key")
    if not product_key or not variant_key:
        return {"eligibility_status": "unknown", "verification_status": "unknown", "coverage_status": "none", "reason": "missing_catalog_identifier", "evidence": []}
    context = {key: slots.get(key) for key in ("age_months", "weight_kg", "independent_sitting") if slots.get(key) is not None}
    request = SearchRequest(domain="baby", product_key=product_key, variant_key=variant_key, query="연령, 체중 및 독립 착석 조건", market=candidate.get("market", "KR"), language="ko", corpus="real", purpose="validation", recommendation_run_id=str(run_id), context=context)
    verified = verify_baby_manual(rag_service, request, **context)
    if verified.get("status") == "error":
        return {"eligibility_status": "unknown", "verification_status": "unknown", "coverage_status": "error", "reason": verified.get("error_code", "retrieval_error"), "evidence": []}
    validation_id = engine_repo.add_validation(run_id, rule_key="baby_manual_applicability", rule_version="v1", executor_version="rag-v1", status=verified.get("eligibility_status", "unknown"), severity="critical", measured_values=context, threshold={}, message=verified.get("reason", "manual verification"), checked_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    engine_repo.link_validation_target(validation_id, candidate_id=candidate["candidate_id"])
    explanation = explain_manual(rag_service, request)
    evidence = []
    profile_id = rag_service.repo.active_profile()["id"]
    for hit in explanation.get("hits", []):
        resolved = rag_service.repo.resolve_evidence(hit["evidence_id"], request, profile_id)
        if resolved:
            engine_repo.link_candidate_evidence(candidate["candidate_id"], hit["evidence_id"], "manual_excerpt")
            engine_repo.link_validation_evidence(validation_id, hit["evidence_id"])
            evidence.append(hit)
    return {"eligibility_status": verified.get("eligibility_status", "unknown"), "verification_status": verified.get("verification_status", "unknown"), "coverage_status": verified.get("coverage_status", "partial"), "reason": verified.get("reason"), "evidence": evidence, "explanation": explanation.get("answer"), "error_code": explanation.get("error_code")}


def _conditions_summary(cat_def: dict, values: dict) -> str:
    from src.services import session_service
    fields = session_service._build_fields(cat_def, values)
    parts = [f["display"] for f in fields if f["status"] == "confirmed" and f["display"]]
    return " · ".join(parts)


def get_stored_result(conn, revision_id: UUID) -> dict | None:
    """GET /result 가 호출 — 저장된 실행/후보/검증만 읽어 RecommendResult 모양으로 조립한다.

    폴링 대상: status가 running이면 items/verification/explanation은 아직 비어있거나 pending.
    """
    from src.repo.engine_repo import EngineRepo
    from src.repo.plan_repo import PlanRepo
    from src.repo.product_repo import ProductRepo

    erepo, prepo, prodrepo = EngineRepo(conn), PlanRepo(conn), ProductRepo(conn)
    run = erepo.get_latest_run(revision_id)
    if run is None:
        return None

    revision = prepo.get_revision(revision_id)
    full = prepo.load_full(revision_id)
    values = {row["condition_key"]: row["value"].get("value") for row in full["conditions"]}
    category = values.get("category")
    cat_def = load_category(category) if category else {}

    status = {"queued": "running", "running": "running", "completed": "done",
              "failed": "failed", "stale": "failed"}.get(run["status"], run["status"])

    result: dict = {
        "list_id": str(revision["plan_id"]), "run_id": str(run["id"]), "status": status,
        "progress": [
            {"step": "conditions", "label": "조건 정리", "status": "done"},
            {"step": "candidates", "label": "후보 수집", "status": "done" if status != "running" else "running"},
        ],
        "category": category, "conditions_summary": _conditions_summary(cat_def, values) if cat_def else "",
        "budget_max": values.get("budget_max"),
        "items": [], "totals": None,
        "verification": {"status": "pending", "confidence": None, "issues": []},
        "explanation": {"status": "pending", "text": None},
        "reasoning_log": run.get("reasoning_log") or [],
        "data_notice": "상품·가격·리뷰는 합성 데이터입니다.",
    }
    if status == "failed":
        result["error"] = {"code": "recommend_failed", "message": "추천을 만드는 중 오류가 발생했어요."}
        return result
    if status == "running":
        return result

    candidates_by_slot = prodrepo.candidates_by_slot()
    items = []
    for row in erepo.get_candidates(run["id"]):
        attrs = row.get("attributes") or {}
        spec_summary = f"성능 티어 {attrs['perf_tier']}" if attrs.get("perf_tier") is not None else None
        price = int(row["price"]) if row["price"] is not None else 0
        slot_variants = candidates_by_slot.get(row["slot"], [])
        alternatives_count = sum(1 for c in slot_variants if c["variant_id"] != row["variant_id"])
        items.append({
            "item_id": str(row["id"]), "slot": row["slot"], "slot_label": row["slot_label"],
            "product": {
                "product_key": row["product_key"], "variant_id": str(row["variant_id"]),
                "name": row["product_name"], "brand": row["brand"] or "",
                "spec_summary": spec_summary, "image_url": row["image_url"],
                "purchase_url": row["purchase_url"],
            },
            "price": price, "price_source": "synthetic",
            "price_observed_at": row["observed_at"].isoformat() if row["observed_at"] else None,
            "qty": row["qty"], "selected": row["selected"], "timing": row["timing"], "budget_share": None,
            "review": None,
            "reason": {"status": row["reason_status"], "text": row["reason"]},
            "checks": {"status": "pending", "text": None},
            "alternatives_count": alternatives_count,
        })
    selected_price = sum(i["price"] * i["qty"] for i in items if i["selected"])
    selected_units = sum(i["qty"] for i in items if i["selected"])
    for item in items:
        item["budget_share"] = round(item["price"] * item["qty"] / selected_price, 3) if item["selected"] and selected_price else None
    budget_max = values.get("budget_max")
    result["items"] = items
    result["totals"] = {
        "selected_price": selected_price, "selected_units": selected_units,
        "budget_remaining": (budget_max - selected_price) if budget_max else None,
        "over_budget": bool(budget_max and selected_price > budget_max),
    }

    validations = erepo.get_validations(run["id"])
    penalty = sum((v["measured_values"] or {}).get("penalty", 0) for v in validations)
    confidence = max(0, 100 - penalty)
    result["verification"] = {
        "status": "ready", "confidence": confidence,
        "issues": [
            {"axis": v["rule_key"], "severity": "major" if v["severity"] in ("warning", "critical") else "minor", "text": v["message"]}
            for v in validations
        ],
    }
    result["explanation"] = {
        "status": run.get("explanation_status") or "pending",
        "headline": run.get("explanation_headline"),
        "text": run.get("explanation_text"),
    }
    return result


# ── 결과 화면 상호작용 (§D-4-2: 담기/빼기·수량·구매시점 / 후보 교체 / 결과 대화) ──

def _require_done_run(conn, revision_id: UUID) -> tuple:
    from src.repo.engine_repo import EngineRepo
    erepo = EngineRepo(conn)
    run = erepo.get_latest_run(revision_id)
    if run is None or run["status"] != "completed":
        raise NotFound("추천 결과가 없습니다. 먼저 /recommend 를 호출하세요.")
    return erepo, run


def _find_candidate(rows: list[dict], item_id: UUID) -> dict:
    for row in rows:
        if row["id"] == item_id:
            return row
    raise NotFound("해당 품목을 찾을 수 없습니다.")


def patch_item(conn, revision_id: UUID, item_id: UUID, *, selected: bool | None,
                qty: int | None, timing: str | None) -> dict:
    erepo, run = _require_done_run(conn, revision_id)
    _find_candidate(erepo.get_candidates(run["id"]), item_id)
    erepo.update_candidate_state(item_id, selected=selected, qty=qty, timing=timing)
    return get_stored_result(conn, revision_id)


def _alternative_out(row: dict, *, current: bool, current_price: int) -> dict:
    price = int(row["price"]) if row.get("price") is not None else 0
    delta = price - current_price
    label = "현재 선택" if current else ("절약형 후보" if delta < 0 else ("프리미엄 후보" if delta > 0 else "동급 후보"))
    attrs = row.get("attributes") or {}
    return {
        "candidate_id": str(row["variant_id"]), "label": label, "current": current,
        "product": {
            "product_key": row.get("product_key") or str(row["product_id"]),
            "variant_id": str(row["variant_id"]), "name": row["name"], "brand": row.get("brand") or "",
            "spec_summary": f"성능 티어 {attrs['perf_tier']}" if attrs.get("perf_tier") is not None else None,
            "image_url": row.get("image_url"), "purchase_url": row.get("purchase_url"),
        },
        "price": price, "price_delta": delta, "review": None,
    }


def list_alternatives(conn, revision_id: UUID, item_id: UUID) -> dict:
    from src.repo.product_repo import ProductRepo
    erepo, run = _require_done_run(conn, revision_id)
    current = _find_candidate(erepo.get_candidates(run["id"]), item_id)
    current_price = int(current["price"]) if current["price"] is not None else 0
    slot_variants = ProductRepo(conn).candidates_by_slot().get(current["slot"], [])
    items = [
        _alternative_out(row, current=False, current_price=current_price)
        for row in sorted(slot_variants, key=lambda r: r["price"] if r["price"] is not None else 0)
        if row["variant_id"] != current["variant_id"]
    ]
    return {"items": items}


def swap_item(conn, revision_id: UUID, item_id: UUID, candidate_id: UUID) -> dict:
    """candidate_id는 alternatives가 돌려준 variant_id다. item_id(행 자체)는 그대로 두고
    내용만 바꿔치기한다 — 계약상 item_id는 후보 교체 후에도 고정."""
    from src.repo.product_repo import ProductRepo
    erepo, run = _require_done_run(conn, revision_id)
    current = _find_candidate(erepo.get_candidates(run["id"]), item_id)
    slot_variants = ProductRepo(conn).candidates_by_slot().get(current["slot"], [])
    target = next((row for row in slot_variants if row["variant_id"] == candidate_id), None)
    if target is None:
        raise NotFound("해당 후보를 찾을 수 없습니다.")
    erepo.update_candidate_variant(item_id, variant_id=candidate_id,
                                    offer_observation_id=target.get("offer_observation_id"))
    # update_candidate_variant 가 reason 을 pending 으로 되돌리는데 다시 채우는 경로가 없어서 화면의
    # "추천 이유" 가 영원히 "정리하는 중…" 이었다. [5] 를 다시 돌릴 수 없으니(rank·build 는 메모리에만
    # 있었다) 코드가 아는 사실만으로 한 줄 적는다 — 판단이 아니라 교체 기록이다.
    old_price = int(current["price"]) if current["price"] is not None else 0
    new_price = int(target["price"]) if target.get("price") is not None else 0
    erepo.update_candidate_reason(item_id, (
        f"사용자 요청으로 교체한 부품입니다 — 자동 추천은 '{current['product_name']}'({old_price:,}원)였고 "
        f"이 후보는 {new_price - old_price:+,}원입니다. 순위·검증 점수는 교체 전 구성 기준입니다."))
    return get_stored_result(conn, revision_id)


_SLOT_SYNONYMS: dict[str, str] = {
    "그래픽카드": "GPU", "그래픽": "GPU", "지포스": "GPU", "라데온": "GPU", "gpu": "GPU",
    "씨피유": "CPU", "프로세서": "CPU", "cpu": "CPU",
    "램": "RAM", "메모리": "RAM", "ram": "RAM",
    "메인보드": "메인보드", "마더보드": "메인보드",
    "저장장치": "저장장치", "에스에스디": "저장장치", "ssd": "저장장치", "하드": "저장장치",
    "파워": "파워", "전원": "파워",
    "케이스": "케이스",
    "쿨러": "쿨러", "쿨링": "쿨러",
}
_CHEAPER_WORDS = ("저렴", "싸게", "싼", "가성비", "낮은", "절약")
_PRICIER_WORDS = ("고급", "좋은", "성능", "비싼", "상위", "프리미엄")


def _match_slot(text: str, known_slots: set[str]) -> str | None:
    lowered = text.lower()
    for keyword, slot in _SLOT_SYNONYMS.items():
        if keyword in lowered and slot in known_slots:
            return slot
    return next((slot for slot in known_slots if slot.lower() in lowered), None)


def handle_result_message(conn, revision_id: UUID, text: str) -> dict:
    """결과 화면 채팅. 에이전트(RESULT_AGENT=1)가 있으면 도구 호출로 후보 조회·교체·담기/빼기·근거 설명을
    처리하고, 없거나 실패하면 아래 규칙 경로 — "그래픽카드를 더 저렴한 걸로" 같은 요청만 해석하고
    슬롯·방향을 못 찾으면 아무것도 바꾸지 않고 이해하지 못했다는 답만 돌려준다."""
    from src.agent import result_agent
    if result_agent.available():
        _require_done_run(conn, revision_id)
        try:
            turn = result_agent.run_turn(conn, revision_id, get_stored_result(conn, revision_id), text)
            log.info("result agent [%s]: %s", revision_id, " | ".join(turn.trace) or "(도구 호출 없음)")
            return {"reply": turn.reply, "result": turn.result}
        except Exception as exc:  # noqa: BLE001 — 모델·네트워크 오류는 이번 턴만 규칙으로
            log.warning("result agent failed, falling back to rules: %s", exc)
            import psycopg
            if isinstance(exc, psycopg.Error):
                conn.rollback()        # 실패한 트랜잭션 위에서는 규칙 경로의 SQL 도 전부 거부된다

    erepo, run = _require_done_run(conn, revision_id)
    rows = erepo.get_candidates(run["id"])
    known_slots = {r["slot"] for r in rows}
    slot = _match_slot(text, known_slots)
    if slot is None:
        return {"reply": "무엇을 바꿀지 이해하지 못했어요. 부품 이름(예: 그래픽카드)과 원하시는 "
                          "방향(더 저렴한/더 좋은)을 함께 말씀해 주세요.",
                "result": get_stored_result(conn, revision_id)}
    cheaper = any(w in text for w in _CHEAPER_WORDS)
    pricier = any(w in text for w in _PRICIER_WORDS)
    if not cheaper and not pricier:
        return {"reply": f"{slot}를 어떻게 바꿔드릴까요? '더 저렴한 걸로' 또는 '더 좋은 걸로'처럼 말씀해 주세요.",
                "result": get_stored_result(conn, revision_id)}

    current = next(r for r in rows if r["slot"] == slot)
    current_price = int(current["price"]) if current["price"] is not None else 0
    from src.repo.product_repo import ProductRepo
    slot_variants = ProductRepo(conn).candidates_by_slot().get(slot, [])
    others = [r for r in slot_variants if r["variant_id"] != current["variant_id"] and r["price"] is not None]
    # "더 저렴한"/"더 좋은"은 방향이 있는 요청이다 — 후보가 있어도 그 방향으로 안 가면
    # (지금이 이미 최저가/최고가) 엉뚱한 방향으로 바꾸지 않고 그렇다고 말한다.
    candidates = [r for r in others if r["price"] < current_price] if cheaper \
        else [r for r in others if r["price"] > current_price]
    if not candidates:
        state = "가장 저렴해요" if cheaper else "가장 고급이에요"
        return {"reply": f"지금 선택된 {slot}가 이미 {state}. 더 {'저렴한' if cheaper else '좋은'} 후보가 없어요.",
                "result": get_stored_result(conn, revision_id)}
    target = min(candidates, key=lambda r: r["price"]) if cheaper else max(candidates, key=lambda r: r["price"])
    # swap_item 을 거쳐야 교체 기록 reason 이 같이 적힌다 (직접 update_candidate_variant 하면 pending 으로 남는다)
    result = swap_item(conn, revision_id, current["id"], target["variant_id"])
    direction = "더 저렴한" if cheaper else "더 좋은"
    reply = f"{slot}를 {direction} '{target['name']}'(으)로 바꿨어요."
    return {"reply": reply, "result": result}
