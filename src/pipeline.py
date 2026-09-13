"""파이프라인 오케스트레이션 (Truefit).

시나리오 파일(data/scenarios/*.json)을 입력으로 8단계를 순서대로 실행한다.
카테고리별 검증 분기:
  computer (verify_branch=set)      : [4] 세트 최적화 → [3-C] 세트 검증  ─(신뢰도<80)⟳
  baby     (verify_branch=per_item) : [3-C] 품목별 검증 → [4] 예산 배분   (데모 미구현)

각 단계 로그는 on_log 콜백으로 흘리고 최종 결과는 PipelineResult(pydantic)로 반환한다.
"""
from __future__ import annotations

import json
from typing import Callable

from src.categories import load_category, verify_branch
from src.config import MAX_RESEARCH_ROUNDS, SCENARIO_DIR
from src.dto import BasketLine, BasketResult, Candidate, PipelineResult, VerificationResult, VerificationTarget
from src.engine import stage1_intent, stage2_requirement, stage3_0_candidates
from src.engine import stage3a_hardfilter, stage3b_rank, stage3c_verify
from src.engine import stage4_optimize, stage5_explain
from src.rag.evidence_search import load_mini_corpus

LogFn = Callable[[str], None]


def load_scenario(name: str) -> dict:
    path = SCENARIO_DIR / f"{name}.json"
    if not path.exists():
        avail = ", ".join(p.stem for p in SCENARIO_DIR.glob("*.json"))
        raise FileNotFoundError(f"시나리오 없음: {name}  (사용 가능: {avail})")
    return json.loads(path.read_text(encoding="utf-8"))


def run_pipeline(scenario_name: str, on_log: LogFn = print) -> PipelineResult:
    scenario = load_scenario(scenario_name)
    cat = scenario["category"]
    cat_def = load_category(cat)
    load_mini_corpus(scenario.get("corpus", []))

    result = PipelineResult(scenario=scenario_name, category=cat, input_text=scenario["input_text"])

    def log(msg: str) -> None:
        result.logs.append(msg)
        on_log(msg)

    log(f"입력: {scenario['input_text']!r}")
    log(f"카테고리: {cat_def['label']} · 모드: {scenario['mode']} · 검증분기: {cat_def['verify_branch']}")
    log("")

    # ── ② 공통 단계 ──────────────────────────────────────────────────
    result.slots = stage1_intent.run(scenario, cat_def, log); log("")
    result.requirement = stage2_requirement.run(result.slots, cat_def, log); log("")
    by_slot = stage3_0_candidates.run(result.requirement, log); log("")
    result.hard_filter = stage3a_hardfilter.run(result.requirement, by_slot, log); log("")
    result.rank = stage3b_rank.run(result.hard_filter, result.requirement, result.slots, log); log("")

    # ── ③ 카테고리별 검증 분기 ──────────────────────────────────────
    branch = verify_branch(cat)
    if branch == "set":
        log("── 분기: 컴퓨터 → [4] 세트 최적화 먼저, 그다음 [3-C] 세트 검증 ──")
        _run_computer_branch(scenario, result, log)
    else:
        log("── 분기: 유아 → [3-C] 품목별 검증 먼저, 그다음 [4] 예산 배분 ──")
        raise NotImplementedError("pipeline: 유아 per_item 분기 미구현 (데이터 확보 후)")
    log("")

    # ── ④ 설명 ─────────────────────────────────────────────────────
    result.explanation = stage5_explain.run(result.build, result.verification, log, rank=result.rank)
    log("")
    log("파이프라인 종료.")
    return result


def _run_computer_branch(scenario: dict, result: PipelineResult, log: LogFn) -> None:
    spec, rank = result.requirement, result.rank
    exclude: set[tuple[str, str]] = set()

    for round_no in range(1, MAX_RESEARCH_ROUNDS + 1):
        result.build = stage4_optimize.run(
            rank, spec, log, exclude=exclude, round_no=round_no)
        log("")
        result.verification = stage3c_verify.verify_set(
            result.build, scenario, round_index=round_no - 1, log=log)

        if result.verification.targets[0].passed:
            log(f"      → {round_no}라운드 만에 통과.")
            return

        ps = stage3c_verify.problem_slot(scenario, round_index=round_no - 1)
        ranked = rank.slots.get(ps, {}).get("ranked", []) if ps else []
        if ps and ranked and round_no < MAX_RESEARCH_ROUNDS:
            worst = Candidate.model_validate(ranked[0])
            exclude.add((ps, worst.product_key))
            log(f"      ⟳ 재탐색: 문제 슬롯 {ps} 후보 '{worst.name}' 제외 → [4] 세트 재구성")
            log("")
        else:
            log(f"      ! 재탐색 {round_no}회 소진 → best-so-far + '검증 미완료' 표시")
            return


def run_baby_db_pipeline(*, list_id: str, candidates: list[dict], slots: dict, budget_max: int | None = None) -> tuple[BasketResult, VerificationResult]:
    """DB 카탈로그에서 이미 범위가 결정된 baby 후보를 처리한다.

    이 경로는 scenario JSON과 전역 미니 코퍼스를 읽지 않는다. RAG 검증 주입은 다음
    단계에서 수행한다. product_key/variant_key가 없는 후보는 설명서 검증 대상이 아니다.
    """
    selected: list[BasketLine] = []
    targets: list[VerificationTarget] = []
    total = 0
    for raw in candidates:
        product_key, variant_key = raw.get("product_key"), raw.get("variant_key")
        name, price = raw.get("name", ""), int(raw.get("price", 0))
        if not product_key or not variant_key:
            targets.append(VerificationTarget(subject=name or "미식별 후보", passed=False, gray_axes=["missing_catalog_identifier"], transcript=[{"reason": "missing_catalog_identifier"}]))
            continue
        if budget_max is not None and total + price > budget_max:
            targets.append(VerificationTarget(subject=name, passed=False, gray_axes=["budget_exceeded"], transcript=[{"reason": "budget_exceeded"}]))
            continue
        selected.append(BasketLine(category="baby", sub_item=raw.get("slot", "item"), product_key=product_key, name=name, price=price, score=float(raw.get("score", 0))))
        total += price
        targets.append(VerificationTarget(subject=name, passed=False, gray_axes=["manual_verification_pending"], transcript=[{"product_key": product_key, "variant_key": variant_key}]))
    basket = BasketResult(list_id=list_id, buy_now=selected, totals={"total": total, "currency": "KRW"}, budget={"max": budget_max, "remaining": None if budget_max is None else budget_max-total})
    return basket, VerificationResult(list_id=list_id, category="baby", mode="per_item", targets=targets)
