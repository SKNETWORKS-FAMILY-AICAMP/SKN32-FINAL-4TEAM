"""추천 서비스 — [추천 실행] → 엔진 파이프라인 → 결과 영속화.

계약: docs/frontend_외부수정요청.md §D-4-2 (202 접수 + GET /result 폴링).
start_recommendation() 이 요청 트랜잭션 안에서 run 행만 만들고 즉시 반환하고,
execute_recommendation() 이 백그라운드 태스크(자체 커넥션)에서 엔진을 실제로 돌려 저장한다.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import UUID

from src.categories import load_category
from src.dto import PipelineResult, Slots
from src.errors import Conflict, NotFound, ValidationFailed
from src.pipeline import run_pipeline as _run_scenario


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
    values = {row["condition_key"]: (row["value"] if row["condition_key"] == "age_months" else row["value"].get("value")) for row in full["conditions"]}
    category = values.get("category")
    if category is None:
        raise Conflict("카테고리를 먼저 선택하세요.", code="category_required")
    if category not in ("computer", "baby"):
        raise ValidationFailed(f"지원하지 않는 카테고리입니다: {category}", field="category")

    cat_def = load_category(category)
    from src.services import session_service
    missing = session_service.compute_missing(cat_def, values)
    if missing:
        raise ValidationFailed(f"필수 조건이 아직 안 채워졌습니다: {missing}", field="conditions", code="conditions_incomplete")
    # run 생성 전에(스텝 1) 동시 실행을 막는다 — has_running_run 과 start_run 사이의
    # 경합은 engine.recommendation_run 에 (revision_id) status='running' 부분 유니크
    # 인덱스가 없으면 완전히 막히지 않으나, 같은 트랜잭션 안에서 먼저 체크해 대부분의
    # 경합을 잡는다. 완전한 직렬화는 이 함수가 이미 revision 행을 잠그지 않으므로
    # remaining 으로 기록한다(0011/0012 인덱스 목록에 부분 유니크가 없음).
    if erepo.has_running_run(revision_id):
        raise Conflict("이미 추천을 실행하는 중입니다.", code="run_in_progress")

    if category == "computer":
        run_id = erepo.start_run(
            revision_id, revision["domain_version_id"],
            input_snapshot={"values": values, "strategy": strategy},
            input_hash=hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest(),
            draft_lock_version=revision["lock_version"],
            engine_versions={"pipeline": "computer-v1"},
        )
        return {"run_id": str(run_id), "status": "running"}

    # P2 returns pure IDs; persist them first so the snapshot carries real
    # planning.requirement UUIDs from this revision.
    normalized = session_service.normalize_baby_conditions(values)
    normalized["revision_id"] = str(revision_id)
    domain_snapshot = _baby_domain_snapshot()
    from src.engine.stage2_requirement import build_baby_requirements, persist_baby_requirements
    requirements = persist_baby_requirements(conn, revision_id, build_baby_requirements(normalized, domain_snapshot))
    snapshot = {"values": values, "normalized_conditions": normalized,
                "domain_snapshot": domain_snapshot, "requirement_ids": [r.id for r in requirements],
                "strategy": strategy}
    run_id = erepo.start_run(
        revision_id, revision["domain_version_id"], input_snapshot=snapshot,
        input_hash=hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest(),
        draft_lock_version=revision["lock_version"],
        engine_versions={"pipeline": "baby-v3", "requirements": "baby-rules-v3"},
    )
    return {"run_id": str(run_id), "status": "running"}


def _baby_domain_snapshot() -> dict:
    from src.engine.stage2_requirement import load_baby_rules_snapshot
    return {
        "reference_date": datetime.now(timezone.utc).date().isoformat(),
        "baby_rules_snapshot": load_baby_rules_snapshot(),
    }


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
    try:
        with get_conn() as conn:
            prepo, erepo, prodrepo = PlanRepo(conn), EngineRepo(conn), ProductRepo(conn)
            # P5 review R4: use the conditions frozen into THIS run's input_snapshot at
            # start_recommendation time, not a fresh re-query of plan_condition — the
            # background task can run well after the request, during which the user
            # may have edited conditions; execution must reproduce the input that was
            # true at start, not whatever is true now (stale-completion handling in
            # complete_run already covers publishing the result, this covers the
            # computation itself being reproducible).
            run = erepo.get_run(run_id)
            if run is None:
                raise ValueError("recommendation_run_not_found")
            snapshot = run["input_snapshot"] or {}
            values = snapshot.get("values") or {}
            category = values.get("category")
            if category is None:
                raise ValueError("run_input_snapshot_missing_category")
            if category == "baby":
                conditions = snapshot.get("normalized_conditions") or {}
                _execute_baby_recommendation(conn, prepo, erepo, revision_id, run_id, conditions)
                erepo.complete_run(run_id)
                return
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
            # rank 를 넘겨야 [3-B] 가 후보에 남긴 리뷰 관측 플래그를 [5] 가 읽는다.
            # 빼면 모든 슬롯이 "관측 없음" 이 되고, 감점만 남고 근거가 사라진다 (기본값이 None 이라 조용히).
            explanation = stage5_explain.run(build, verification, noop, rank=rank)

            reason_by_slot = {it.slot: it.reason for it in explanation.items}
            for item in build.items:
                variant_id = prodrepo.variant_id_by_model(item.name)
                if variant_id is None:
                    continue  # 카탈로그 미적재 — 이 슬롯은 저장 못 함, 나머지는 계속 진행
                offer_observation_id = prodrepo.offer_observation_id_by_variant(variant_id)
                erepo.add_candidate(
                    run_id, req_id_by_slot[item.slot], variant_id, result="selected",
                    score=item.score, score_method_version="v1", reason=reason_by_slot.get(item.slot),
                    offer_observation_id=offer_observation_id,
                )

            for issue in verification.targets[0].issues if verification.targets else []:
                erepo.add_validation(
                    run_id, rule_key=issue.axis, rule_version="v1", executor_version="v1",
                    status="fail" if issue.penalty >= 15 else "unknown",
                    severity="warning" if issue.penalty >= 15 else "info",
                    measured_values={"penalty": issue.penalty, "confidence": verification.targets[0].confidence},
                    threshold={}, message=issue.judge or issue.axis,
                    checked_at=datetime.now(timezone.utc),
                )

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
            erepo.complete_run(run_id)
    except Exception:  # noqa: BLE001 — 실패해도 running으로 영원히 남지 않게 별도 커넥션으로 failed 처리
        with get_conn() as fail_conn:
            fail_conn.execute(
                "UPDATE engine.recommendation_run SET status='failed', completed_at=now(), updated_at=now() "
                "WHERE id=%s AND status='running'",
                (run_id,),
            )
        raise


def _execute_baby_recommendation(conn, prepo, erepo, revision_id: UUID, run_id: UUID, conditions: dict) -> None:
    """백그라운드에서 실행되는 유아 경로 [3-0]→[3-C]→[4]→저장.

    `conditions`는 start_recommendation이 실행 트랜잭션에서 정규화해 run.input_snapshot에
    얼려 둔 그대로다(P5 review R4) — 여기서 plan_condition을 다시 읽거나 재정규화하지
    않는다. 백그라운드 실행이 지연되는 동안 사용자가 조건을 바꿨더라도, 이 실행은 시작
    시점의 입력을 재현해야 한다(조건 변경으로 인한 stale 처리는 complete_run이 별도로
    담당한다 — 이건 계산 자체의 재현성 문제다).

    persist_baby_requirements 는 이미 start_recommendation(요청 트랜잭션)에서 실행됐다 —
    여기서는 그 결과를 다시 읽기만 한다(재계산 아님). 후보 수집(get_baby_candidates)은
    DB 읽기뿐이라 재호출해도 새 검색/임베딩이 아니다. RAG 검증(verify_baby_candidate)만
    실제로 임베딩을 쓰므로, 그 부분만 이 백그라운드 태스크 안에서 수행한다
    (CONTRACTS "No external embedding inside a long plan transaction").
    """
    from src.engine.stage2_requirement import load_persisted_baby_requirements
    from src.engine.stage3_0_candidates import get_baby_candidates
    from src.engine.stage3b_rank import load_baby_optimizer_profile
    from src.engine.stage5_explain import explain_baby_candidate
    from src.pipeline import run_baby_optimizer
    from src.rag.provider import get_search_provider
    from src.rag.service import RagService
    from src.repo.material_repo import MaterialRepo

    requirements = load_persisted_baby_requirements(conn, revision_id)
    candidates_by_req = get_baby_candidates(conn, requirements, corpus="synthetic")

    # 후보마다 실제 recommendation_candidate 행을 먼저 만든다 — verify_and_persist_baby_candidate
    # (persist_candidate_check)가 "이 run 에 속한 실제 행"을 전제하기 때문이다(P3 계약).
    # BabyCandidate.candidate_id 를 카탈로그 offer_observation_id 에서 이 행의 진짜 UUID로 바꿔치기한다.
    db_candidates = []
    for requirement in requirements:
        for cand in candidates_by_req.get(requirement.id, []):
            if cand.variant_id is None:
                continue
            db_id = erepo.add_candidate(
                run_id, UUID(requirement.id), UUID(cand.variant_id), result="pending",
                offer_observation_id=UUID(cand.offer_observation_id) if cand.offer_observation_id else None,
            )
            db_candidates.append((cand, cand.model_copy(update={"candidate_id": str(db_id)})))

    rag_service = RagService(MaterialRepo(conn), get_search_provider())
    run_context = {"recommendation_run_id": str(run_id)}
    checks = []
    for _catalog_cand, db_cand in db_candidates:
        outcome = verify_and_persist_baby_candidate(
            conn=conn, rag_service=rag_service, run_id=run_id,
            candidate=db_cand.model_dump(), conditions=conditions,
        )
        check = outcome["check"]
        checks.append(check)
        explanation = explain_baby_candidate(rag_service, db_cand.model_dump(), check, run_context)
        reason_status = explanation.status if explanation.status in ("ready", "failed") else "pending"
        erepo.set_candidate_reason(UUID(db_cand.candidate_id), reason=explanation.text, status=reason_status)

    profile = load_baby_optimizer_profile()
    ranked, decision = run_baby_optimizer(
        requirements=requirements, candidates=[c for _o, c in db_candidates], checks=checks,
        owned_items=[], budget_max=conditions.get("budget_max"), profile=profile,
    )

    selected_candidate_ids = {it.candidate_id for it in decision.items if it.candidate_id and it.selected}
    for _o, db_cand in db_candidates:
        result = "selected" if db_cand.candidate_id in selected_candidate_ids else "rejected"
        score = next((s.score for s in ranked.by_requirement.get(db_cand.requirement_id, [])
                     if s.candidate_id == db_cand.candidate_id), None)
        erepo.set_candidate_result(UUID(db_cand.candidate_id), result=result, score=score)

    # develop v3 stores mutable state on recommendation_candidate.  Do not recreate planning.item.
    req_by_id = {r.id: r for r in requirements}
    cand_by_id = {c.candidate_id: c for _o, c in db_candidates}
    by_candidate = {it.candidate_id: it for it in decision.items if it.candidate_id}
    for _raw, candidate in db_candidates:
        item = by_candidate.get(candidate.candidate_id)
        erepo.update_candidate_state(
            UUID(candidate.candidate_id), selected=bool(item and item.selected),
            qty=int(item.qty) if item else 1, timing=item.timing if item else "now",
        )

    headline = "예산 안에서 필요한 품목을 담았어요." if decision.feasible else "예산 안에서 채울 수 없는 필수 품목이 있어요."
    lines = []
    for it in decision.items:
        if it.status == "to_purchase" and it.selected:
            req = req_by_id.get(it.requirement_id)
            cand = cand_by_id.get(it.candidate_id) if it.candidate_id else None
            lines.append(f"{req.slot_key if req else '?'}: {cand.name if cand else '?'} "
                        f"{int(it.unit_price or 0):,}원 x {it.qty:g}")
    for miss in decision.missing_requirements:
        lines.append(f"미충족: {miss.get('slot_key')} (필요 {miss.get('required_qty')}) — {miss.get('reason')}")
    trace = [
        {"step": "조건 정리", "title": "조건 정리", "detail": f"필요 항목 {len(requirements)}개"},
        {"step": "후보 검증", "title": "후보 검증",
         "detail": f"후보 {len(db_candidates)}개 중 선택 {len(selected_candidate_ids)}개"},
        {"step": "예산 배분", "title": "예산 배분", "detail": headline},
    ]
    erepo.set_explanation(
        run_id, headline=headline,
        text="\n".join(lines) if lines else headline,
        reasoning_log=trace,
    )

    from src.services import feedback_service
    revision = prepo.get_revision(revision_id)
    feedback_service.emit_shown(
        conn, plan_id=revision["plan_id"], revision_id=revision_id, run_id=run_id,
        version=revision["lock_version"],
    )


def verify_and_persist_baby_candidate(*, conn, rag_service, run_id, candidate: dict, conditions: dict) -> dict:
    """후보 하나의 검증(verify_baby_candidate)과 설명(explain_baby_candidate)을 각자
    별도의 RAG 질의로 수행하고, persist_candidate_check로 원자적으로 저장한다.

    이전 verify_and_explain_baby_candidate는 검증과 설명에 동일한 SearchRequest를
    재사용해 explanation hit이 항상 validation hit과 같아지는 결함이 있었다(P3
    CONTRACTS VE05). verify_baby_candidate/explain_baby_candidate는 서로 다른 질의를
    쓰므로 인용 근거가 실제로 달라질 수 있다 — 이것이 실제 동작이지 버그가 아니다.
    """
    from src.engine.stage3c_verify import verify_baby_candidate
    from src.engine.stage5_explain import explain_baby_candidate
    from src.repo.engine_repo import persist_candidate_check

    run_context = {"recommendation_run_id": str(run_id)}
    check = verify_baby_candidate(rag_service, candidate, conditions, run_context)
    explanation = explain_baby_candidate(rag_service, candidate, check, run_context)
    persist_candidate_check(conn, run_id, candidate["candidate_id"], check, explanation)
    return {"check": check, "explanation": explanation}


def _load_baby_basket_items(erepo, revision_id: UUID, requirements) -> tuple[list, list, dict]:
    """Rebuild v3 baby output from requirement ownership and candidate rows.

    develop has no planning.item: owned rows are derived from match_spec/condition
    coverage and purchase rows are the persisted recommendation_candidate state.

    P5 review R2: baby's stable HTTP item_id is the requirement UUID, not a
    candidate UUID — a requirement can have many evaluated candidate rows (one per
    option verified during execution), so this emits exactly one to_purchase row per
    requirement (whichever candidate is currently `selected`), never one per raw
    candidate row.
    """
    from src.dto import BasketItem, CandidateCheck

    req_by_id = {r.id: r for r in requirements}
    items, checks, row_by_item_id = [], [], {}
    for req in requirements:
        for owned in req.owned:
            qty = float(owned.get("qty", 0))
            if qty <= 0:
                continue
            items.append(BasketItem(
                item_id=f"owned:{req.id}:{owned.get('source_condition_id', 'unknown')}",
                requirement_id=req.id, group_key=req.group_key, status="owned", selected=False,
                qty=qty, unit_code=req.unit_code, unit_qty=1, timing=req.timing,
                validation={"source": "owned_coverage"},
            ))
    run = erepo.get_latest_run(revision_id)
    if run is None:
        return items, checks, row_by_item_id
    selected_by_requirement: dict[str, dict] = {}
    for row in erepo.get_candidates(run["id"]):
        if row["selected"] and str(row["requirement_id"]) in req_by_id:
            selected_by_requirement[str(row["requirement_id"])] = row
    for requirement_id, row in selected_by_requirement.items():
        req = req_by_id[requirement_id]
        candidate_id = str(row["id"])
        eligibility = erepo.get_candidate_eligibility(run["id"], row["id"])
        row_by_item_id[requirement_id] = row
        items.append(BasketItem(
            item_id=requirement_id, requirement_id=requirement_id, group_key=req.group_key,
            candidate_id=candidate_id, variant_id=str(row["variant_id"]), status="to_purchase",
            selected=True, qty=float(row["qty"]), unit_code=req.unit_code,
            unit_qty=float(row["unit_qty"] or 1), timing=row["timing"],
            unit_price=float(row["price"]) if row["price"] is not None else None,
            offer_observation_id=str(row["offer_observation_id"]) if row["offer_observation_id"] else None,
            validation={"eligibility": eligibility["eligibility"]},
        ))
        checks.append(CandidateCheck(
            candidate_id=candidate_id, requirement_id=requirement_id,
            eligibility=eligibility["eligibility"], verification="verified", coverage="none",
            selection_allowed=eligibility["selection_allowed"],
        ))
    return items, checks, row_by_item_id

def _baby_items_and_totals(conn, prepo, erepo, revision_id: UUID, budget_max: int | None):
    """GET/PATCH/swap 이 공유하는 baby 결과 조립 — recalculate_basket()만 쓴다(순수 함수,
    DB/RAG 재호출 없음). CONTRACTS "GET only loads stored result/JSON refs"."""
    from src.engine.stage2_requirement import load_persisted_baby_requirements
    from src.engine.stage4_optimize import recalculate_basket

    requirements = load_persisted_baby_requirements(conn, revision_id)
    basket_items, checks, row_by_item_id = _load_baby_basket_items(erepo, revision_id, requirements)
    decision = recalculate_basket(basket_items, requirements, budget_max, checks)
    req_by_id = {r.id: r for r in requirements}

    out_items = []
    for it in decision.items:
        row = row_by_item_id.get(it.item_id) or {}
        spec = row.get("item_spec") or {}
        req = req_by_id.get(it.requirement_id)
        candidate = erepo.get_candidate(UUID(it.candidate_id)) if it.candidate_id else None
        reason_text = candidate["reason"] if candidate else None
        reason_status = (candidate["reason_status"] if candidate else None) or "pending"
        price = int(it.unit_price) if it.unit_price is not None else 0
        name = row.get("product_name") or spec.get("label") or (req.slot_key if req else it.requirement_id)
        if it.status == "owned":
            # 소유 항목은 구매 검증 대상이 아니다 — pending으로 남기면 프론트 폴링이
            # 끝나지 않는다(tfResultPending). "확인할 것 없음"으로 종결시킨다.
            reason_text, reason_status = "이미 보유하고 있어 추가 구매가 필요 없어요.", "ready"
            checks_status, checks_text = "ready", None
        else:
            checks_status = "ready" if spec.get("eligibility") else "pending"
            checks_text = f"적합성: {spec.get('eligibility')}" if spec.get("eligibility") else None
        out_items.append({
            "item_id": it.item_id, "slot": req.slot_key if req else "?",
            "slot_label": req.slot_key if req else "?",
            "product": {
                "product_key": row.get("product_key") or (it.candidate_id or it.item_id),
                "variant_id": str(row.get("variant_id")) if row.get("variant_id") else it.variant_id,
                "name": name, "brand": row.get("brand") or "",
                "spec_summary": None, "image_url": row.get("image_url"),
                "purchase_url": row.get("purchase_url"),
            },
            "price": price, "price_source": "synthetic", "price_observed_at": None,
            "qty": int(it.qty) if float(it.qty).is_integer() else it.qty,
            "selected": it.selected, "timing": it.timing, "budget_share": None,
            "review": None,
            "reason": {"status": reason_status, "text": reason_text},
            "checks": {"status": checks_status, "text": checks_text},
            "alternatives_count": 0,
            "requirement_id": it.requirement_id, "candidate_id": it.candidate_id,
            "eligibility": spec.get("eligibility"), "coverage": spec.get("coverage"),
            "status": it.status,
        })
    charged = [i for i in out_items if i["status"] == "to_purchase" and i["selected"] and i["timing"] == "now"]
    charged_total = sum(i["price"] * i["qty"] for i in charged) or 0
    for i in out_items:
        i["budget_share"] = round((i["price"] * i["qty"]) / charged_total, 3) if charged_total and i in charged else None
    totals = dict(decision.totals)
    totals["selected_price"] = int(totals.get("selected_price") or 0)
    totals["selected_units"] = int(round(totals.get("selected_units") or 0))
    return out_items, totals, decision.feasible, decision.missing_requirements


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

    erepo, prepo = EngineRepo(conn), PlanRepo(conn)
    run = erepo.get_latest_run(revision_id)
    if run is None:
        return None

    revision = prepo.get_revision(revision_id)
    full = prepo.load_full(revision_id)
    values = {row["condition_key"]: (row["value"] if row["condition_key"] == "age_months" else row["value"].get("value")) for row in full["conditions"]}
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
        "revision_id": str(revision_id), "lock_version": revision["lock_version"],
    }
    if status == "failed":
        result["error"] = {"code": "recommend_failed", "message": "추천을 만드는 중 오류가 발생했어요."}
        return result
    if status == "running":
        return result

    if category == "baby":
        items, totals, feasible, missing = _baby_items_and_totals(conn, prepo, erepo, revision_id, values.get("budget_max"))
        result["items"] = items
        result["totals"] = totals
        result["feasible"] = feasible
        result["missing_requirements"] = missing
        if not feasible:
            result["status"] = "done"  # 계산은 끝났다 — 실패가 아니라 "담을 수 없음"(CONTRACTS)
    else:
        items = []
        for row in erepo.get_candidates(run["id"]):
            attrs = row.get("attributes") or {}
            spec_summary = f"성능 티어 {attrs['perf_tier']}" if attrs.get("perf_tier") is not None else None
            price = int(row["price"]) if row["price"] is not None else 0
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
                "reason": {"status": "ready", "text": row["reason"]} if row["reason"] else {"status": "pending", "text": None},
                "checks": {"status": "pending", "text": None},
                "alternatives_count": 0,
            })
        # develop DEVELOP_DB_TRANSITION.md: "now" 청구 대상만 total, soon/later 는 별도.
        charged = [i for i in items if i["selected"] and i["timing"] == "now"]
        selected_price = sum(i["price"] * i["qty"] for i in charged)
        selected_units = sum(i["qty"] for i in charged)
        for item in items:
            item["budget_share"] = (
                round((item["price"] * item["qty"]) / selected_price, 3)
                if selected_price and item in charged else None
            )
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
        "status": "ready" if run.get("explanation_status") == "ready" else "pending",
        "headline": run.get("explanation_headline"),
        "text": run.get("explanation_text"),
    }
    return result


def get_owned_result(conn, list_id: UUID, principal) -> dict:
    """GET /result 의 소유권 검증 래퍼 — 두 번째 파이프라인이 아니라 get_stored_result 그대로."""
    from src.services import session_service
    revision = session_service.load_owned_draft(conn, list_id, principal)
    stored = get_stored_result(conn, revision["id"])
    if stored is None:
        raise NotFound("추천 실행 결과가 없습니다. 먼저 /recommend 를 호출하세요.")
    return stored


def _require_candidate_item(conn, list_id: UUID, item_id: UUID, principal) -> tuple[dict, "EngineRepo", dict]:
    """PC: item_id == engine.recommendation_candidate.id, one row per slot (develop
    `0013_result_item_interaction.sql` 이 원래 의도한 모양 — 별도 planning.item 없이
    후보 행 자체를 편집한다, P0 v3).

    Baby (P5 review R2/DEVELOP_DB_TRANSITION.md v3): item_id는 안정적인 requirement
    UUID다 — 여기서 현재 run의 그 requirement에 대해 선택된 후보 행으로 resolve한다.
    baby는 후보마다(평가된 것 전부) 별도 행이 이미 있으므로, 반환된 `row`는 그 자체가
    실제 편집 대상이고 `item_id`(=requirement UUID)와는 다른 자기 id를 가진다.

    두 카테고리 모두 revision.id 일치뿐 아니라 **현재(최신) run**인지도 확인한다
    (P5 review R3) — 지나간 run에 속한 후보가 지금 것처럼 편집되지 않게."""
    from src.repo.engine_repo import EngineRepo
    from src.repo.plan_repo import PlanRepo
    from src.services import session_service

    revision = session_service.load_owned_draft(conn, list_id, principal)
    erepo = EngineRepo(conn)
    current_run = erepo.get_latest_run(revision["id"])
    if current_run is None:
        raise NotFound("항목을 찾을 수 없습니다.")

    if revision.get("category") == "baby":
        requirement = PlanRepo(conn)._one(
            "SELECT id FROM planning.requirement WHERE id=%s AND revision_id=%s",
            (item_id, revision["id"]),
        )
        if requirement is None:
            raise NotFound("항목을 찾을 수 없습니다.")
        row = erepo.get_selected_candidate_for_requirement(current_run["id"], item_id)
        if row is None:
            raise NotFound("항목을 찾을 수 없습니다.")
        return revision, erepo, row

    row = erepo.get_candidate(item_id)
    if row is None or str(row["run_id"]) != str(current_run["id"]):
        raise NotFound("항목을 찾을 수 없습니다.")
    return revision, erepo, row


def get_alternatives(conn, list_id: UUID, item_id: UUID, principal) -> dict:
    """GET .../items/{item_id}/alternatives — 이 항목과 같은 requirement 의 다른 후보만."""
    revision, erepo, cand = _require_candidate_item(conn, list_id, item_id, principal)
    rows = erepo.get_candidates_by_requirement(cand["run_id"], cand["requirement_id"])
    current_price = next((int(r["price"]) for r in rows if r["id"] == cand["id"] and r["price"] is not None), None)
    out = []
    for r in rows:
        elig = erepo.get_candidate_eligibility(cand["run_id"], r["id"])
        price = int(r["price"]) if r["price"] is not None else None
        out.append({
            "candidate_id": str(r["id"]), "current": r["id"] == cand["id"],
            "product": {
                "product_key": r["product_key"], "variant_id": str(r["variant_id"]),
                "name": r["product_name"], "brand": r["brand"] or "", "spec_summary": None,
                "image_url": r["image_url"], "purchase_url": r["purchase_url"],
            },
            "price": price,
            "price_delta": (price - current_price) if price is not None and current_price is not None else None,
            "review": None, "selection_allowed": elig["selection_allowed"],
        })
    return {"items": out}


def swap_candidate(conn, list_id: UUID, item_id: UUID, candidate_id: str, principal, *,
                   if_match: int | None) -> dict:
    """POST .../items/{item_id}/swap.

    PC: item_id(행 자체)는 고정, 다른 후보의 상품으로 바꿔치기한다
    (develop `EngineRepo.update_candidate_variant`).

    Baby (P5 review R2): item_id(requirement UUID)는 그대로지만, 상품을 바꿔치기하지
    않는다 — target은 이미 이 requirement에 대해 별도로 검증된 실제 행이므로, 그 행을
    선택하고 기존 선택 행을 해제한다(`select_candidate_exclusive`). 이렇게 해야 각 행의
    evidence_refs/validation이 실제 검증된 상품에 계속 정확히 붙어 있다."""
    from src.repo.plan_repo import PlanRepo
    from src.services import feedback_service

    revision, erepo, cand = _require_candidate_item(conn, list_id, item_id, principal)
    if if_match is None:
        raise ValidationFailed("If-Match(lock_version)이 필요합니다.", field="lock_version")
    prepo = PlanRepo(conn)
    # P5 review R3: lock + re-check under the lock, not the earlier unlocked read —
    # a concurrent request that already bumped the version is now visible here.
    locked = prepo.get_revision_locked(revision["id"])
    if locked is None or if_match != locked["lock_version"]:
        raise Conflict("조건이 변경되어 최신 상태가 아닙니다. 최신 결과를 다시 불러오세요.", code="stale_version")

    target = erepo.get_candidate(UUID(candidate_id))
    if (target is None or str(target["run_id"]) != str(cand["run_id"])
            or str(target["requirement_id"]) != str(cand["requirement_id"])):
        raise ValidationFailed("이 항목의 후보가 아닙니다.", field="candidate_id", code="candidate_out_of_scope")
    elig = erepo.get_candidate_eligibility(cand["run_id"], target["id"])
    if not elig["selection_allowed"]:
        raise ValidationFailed("안전성이 확인되지 않은 후보는 선택할 수 없습니다.",
                              field="candidate_id", code="selection_not_allowed")

    if revision.get("category") == "baby":
        erepo.select_candidate_exclusive(cand["run_id"], cand["requirement_id"], target["id"],
                                         qty=cand["qty"], timing=cand["timing"])
    else:
        erepo.update_candidate_variant(item_id, variant_id=target["variant_id"],
                                       offer_observation_id=target["offer_observation_id"])
    new_version = prepo.bump_lock_version(revision["id"], expected_version=if_match)
    feedback_service.emit_replaced(
        conn, plan_id=revision["plan_id"], revision_id=revision["id"], run_id=cand["run_id"],
        item_id=item_id, version=new_version,
    )
    return get_stored_result(conn, revision["id"])


def update_item(conn, list_id: UUID, item_id: UUID, changes: dict, principal, *,
                if_match: int | None) -> dict:
    """PATCH .../items/{item_id} — selected/qty/timing만 바꾼다. price/total/evidence는 절대 입력받지 않는다."""
    from src.repo.plan_repo import PlanRepo
    from src.services import feedback_service

    revision, erepo, cand = _require_candidate_item(conn, list_id, item_id, principal)
    if if_match is None:
        raise ValidationFailed("If-Match(lock_version)이 필요합니다.", field="lock_version")
    prepo = PlanRepo(conn)
    locked = prepo.get_revision_locked(revision["id"])
    if locked is None or if_match != locked["lock_version"]:
        raise Conflict("조건이 변경되어 최신 상태가 아닙니다. 최신 결과를 다시 불러오세요.", code="stale_version")

    was_selected = cand["selected"]
    selected = changes.get("selected", was_selected)
    if selected:
        # P5 review R3: never persist selected=true without re-checking P3 eligibility
        # here — result-assembly recomputes it for display, but that must not be the
        # only gate on what's actually stored as selected.
        elig = erepo.get_candidate_eligibility(cand["run_id"], cand["id"])
        if not elig["selection_allowed"]:
            raise ValidationFailed("안전성이 확인되지 않은 후보는 선택할 수 없습니다.",
                                  field="selected", code="selection_not_allowed")
    erepo.update_candidate_state(cand["id"], selected=selected, qty=changes.get("qty"), timing=changes.get("timing"))
    new_version = prepo.bump_lock_version(revision["id"], expected_version=if_match)
    if was_selected and not selected:
        feedback_service.emit_removed(
            conn, plan_id=revision["plan_id"], revision_id=revision["id"],
            run_id=cand["run_id"], item_id=item_id, version=new_version,
        )
    return get_stored_result(conn, revision["id"])


# ── result-message: 작은 규칙 집합만 처리 (LLM 미사용, CONTRACTS) ──
_CHEAPER_HINTS = ("싼", "저렴", "낮은")
_SWAP_HINTS = ("바꿔", "교체", "변경")


def handle_result_message(conn, list_id: UUID, text: str, principal) -> dict:
    """POST /session/{id}/result-message — "<슬롯> 더 싼 걸로 바꿔줘" 같은 제한된 문형만 이해한다.
    애매하거나 지원하지 않는 문장은 아무것도 바꾸지 않고 안내만 반환한다."""
    stored = get_owned_result(conn, list_id, principal)
    text_n = (text or "").strip()

    if stored.get("status") != "done":
        return {"reply": "아직 추천 결과가 준비되지 않았어요. 잠시 후 다시 시도해 주세요.", "result": stored}

    if any(h in text_n for h in _CHEAPER_HINTS) and any(h in text_n for h in _SWAP_HINTS):
        target = None
        for item in stored.get("items", []):
            label = item.get("slot_label") or item.get("slot") or ""
            if label and label in text_n:
                target = item
                break
        if target is None and len(stored.get("items", [])) == 1:
            target = stored["items"][0]
        if target is None:
            return {"reply": "어떤 품목을 바꿀지 못 찾았어요. 예: '기저귀 더 싼 걸로 바꿔줘'처럼 품목 이름과 함께 말씀해 주세요.",
                   "result": stored}
        if target["price"] is None:
            return {"reply": f"{target.get('slot_label')}의 현재 가격을 알 수 없어 비교할 수 없어요.", "result": stored}
        alts = get_alternatives(conn, list_id, UUID(target["item_id"]), principal)
        cheaper = [a for a in alts["items"]
                  if a["selection_allowed"] and a["price"] is not None and a["price"] < target["price"]
                  and not a["current"]]
        if not cheaper:
            return {"reply": f"{target.get('slot_label')}에서 지금보다 더 싸면서 선택 가능한 대안을 찾지 못했어요.",
                   "result": stored}
        best = min(cheaper, key=lambda a: a["price"])
        new_result = swap_candidate(conn, list_id, UUID(target["item_id"]), best["candidate_id"], principal,
                                    if_match=stored["lock_version"])
        reply = f"{target.get('slot_label')}을(를) {best['product']['name']}({best['price']:,}원)로 바꿨어요."
        return {"reply": reply, "result": new_result}

    return {"reply": "죄송해요, 아직 이 문장은 이해하지 못해요. 예: '카시트 더 싼 걸로 바꿔줘'처럼 말씀해 주시면 도와드릴게요.",
           "result": stored}
