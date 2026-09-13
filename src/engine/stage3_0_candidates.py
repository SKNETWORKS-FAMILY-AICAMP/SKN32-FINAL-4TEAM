"""[3-0] 후보 수집.

[2]와 [3-A] 사이의 별도 스텝. 실시간 커머스 데이터 API 호출·캐시·재시도를
필터 로직에서 격리한다. 재탐색 시에는 스킵(이미 수집된 후보 재사용).
데모: 로컬 합성 카탈로그만 읽음 (제휴 커머스 API는 최종에서).

get_baby_candidates(conn, requirements, *, corpus) 은 [3-0]의 유아 경로 — DB에서
읽기만 하고(운영은 SQL로 읽는다는 CONTRACTS 원칙), 다른 corpus/카테고리로 대체하지
않는다. 가격 없는/재고 불명확한 행은 조용히 제외되지 상품 없이 무료로 채워지지
않는다. data_gap 규칙(예: 의류)이나 실제로 후보가 없는 슬롯은 빈 리스트로 남아
호출자가 unresolved/missing 목록에 기록한다(P3/P4 몫) — 여기서 예외를 던지지 않는다.
"""
from __future__ import annotations

from src.dto import BabyCandidate, BabyRequirement, Candidate, RequirementSpec
from src.engine import LogFn
from src.repo.catalog_repo import load_candidates_by_slot
from src.repo.product_repo import ProductRepo


def run(spec: RequirementSpec, log: LogFn) -> dict[str, list[Candidate]]:
    log("[3-0] 후보 수집 ...")
    if spec.category == "computer":
        by_slot = load_candidates_by_slot()
        summary = " / ".join(f"{s} {len(c)}" for s, c in by_slot.items())
        log(f"      [MOCK] 합성 카탈로그 로드 → 슬롯별 후보: {summary}")
        return by_slot
    # TODO: 유아 PipelineResult 경로는 get_baby_candidates() 로 대체될 예정 (P5)
    raise NotImplementedError("stage3_0: 유아 후보 수집 미구현 (데이터 확보 후)")


def get_baby_candidates(conn, requirements: list[BabyRequirement], *,
                        corpus: str) -> dict[str, list[BabyCandidate]]:
    repo = ProductRepo(conn)
    out: dict[str, list[BabyCandidate]] = {}
    category_cache: dict[str, list[dict]] = {}
    for requirement in requirements:
        out[requirement.id] = []
        if requirement.constraints.get("data_gap"):
            continue
        # slot_key doubles as category_code for baby (each product has exactly
        # one canonical category; a *need* maps to several slot_keys via YAML).
        category_code = requirement.slot_key
        if category_code not in category_cache:
            category_cache[category_code] = repo.baby_candidates_by_category(
                category_code, corpus=corpus)
        rows = category_cache[category_code]
        candidates = []
        for row in rows:
            candidates.append(BabyCandidate(
                candidate_id=str(row["offer_observation_id"]),
                requirement_id=requirement.id,
                product_id=str(row["product_id"]),
                variant_id=str(row["variant_id"]),
                product_key=row["product_key"],
                variant_key=row["variant_key"],
                name=row["name"],
                slot_key=requirement.slot_key,
                price=int(row["price"]) if row["price"] is not None else None,
                offer_observation_id=str(row["offer_observation_id"]),
                observed_at=row["observed_at"].isoformat() if row["observed_at"] else None,
                stock_status=row["stock_status"],
                pack_quantity=float(row["pack_quantity"]),
                unit_code=row["pack_unit_code"],
                # unit_qty (pieces per pack) has no dedicated DB column — it is
                # carried in variant attributes by seed_baby_catalog.py and MUST be
                # read back here, not defaulted to 1 (R4: was silently dropped).
                unit_qty=float((row.get("variant_attributes") or {}).get("unit_qty", 1)),
                corpus=corpus,
                market=(row.get("attributes") or {}).get("market", "KR"),
                language=(row.get("attributes") or {}).get("language", "ko"),
                facts=(row.get("attributes") or {}).get("facts_by_key", {}),
                score_breakdown={},
            ))
        out[requirement.id] = candidates
        log_count = len(candidates)
        if log_count == 0:
            # Diagnostic gap, not a crash and not a substitution from another corpus/category.
            pass
    return out
