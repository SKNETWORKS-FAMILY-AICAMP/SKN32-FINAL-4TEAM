"""[2] 요구사양 빌드.

슬롯(사용자 언어) → 기계 판정 가능한 목표사양(RequirementSpec).
100% 규칙·룩업. LLM은 extra 자유조건 파싱 / 업그레이드 현재구성 파싱에만 (데모 생략).
컴퓨터: game_requirements + perf_tier 사다리 + PSU 헤드룸 공식 + link_rules 기록.
유아: 월령 → age_fit_table → 필요 카테고리·시점.

build_baby_requirements(conditions, domain_snapshot) 은 [2]의 유아 경로 — develop
`da79839` 정렬(P0 v3) planning.plan_node+requirement 경계에 맞춘 순수 함수다.
config/baby_requirement_rules.yaml (버전 있는 데이터, 코드 아님) 을 읽어 정규화된
conditions 를 list[BabyRequirement] 로 변환한다. DB에 아무것도 쓰지 않는다.
persist_baby_requirements() 가 이 결과를 실제 planning.plan_node/requirement
행(진짜 UUID)으로 옮기는 별도 저장소 연산이다(§CONTRACTS IMPLEMENTATION 5 —
"Persist owned rows ... through a separate repository operation; pure rule
function emits plan changes"). planning.item 은 develop 에 없다 — 보유 출처는
plan_condition UUID로만 표시한다(DEVELOP_DB_TRANSITION.md).

conditions 는 P1 `src.services.session_service.normalize_baby_conditions()` 의
출력(NormalizedConditions) 그대로를 기대한다 — 특히 월령은 최상위 age_months 가
아니라 `age_stage: {"months":int,"label":str,"exact":bool}` 로 들어온다
(2026-09-13 P012 검토 R3: 예전에 최상위 age_months 를 읽던 버그를 수정함). 여기에
호출자가 revision_id 와, 선택적으로 load_baby_rules_snapshot() 이 만든
baby_rules_snapshot 을 추가로 채워 넣는다.
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from functools import lru_cache
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import yaml

from src.dto import BabyRequirement, RequirementSpec, Slots
from src.engine import LogFn

_RULES_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "baby_requirement_rules.yaml"
_TIMING_RANK = {"now": 0, "soon": 1, "later": 2}


class RequirementRuleError(ValueError):
    """config/baby_requirement_rules.yaml 이 없거나 형식이 잘못됨."""


@lru_cache(maxsize=1)
def _load_rules(path: Path = _RULES_PATH) -> dict:
    if not path.exists():
        raise RequirementRuleError(f"규칙 파일 없음: {path}")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    rules = data.get("rules")
    if not rules:
        raise RequirementRuleError("rules 가 비어 있음")
    keys = [r["rule_key"] for r in rules]
    if len(keys) != len(set(keys)):
        raise RequirementRuleError("중복 rule_key")
    for r in rules:
        if not r.get("needs"):
            raise RequirementRuleError(f"{r['rule_key']}: needs 비어 있음")
        if not r.get("data_gap") and not r.get("category_code"):
            raise RequirementRuleError(f"{r['rule_key']}: data_gap 아니면 category_code 필수")
    return data


def _rule_set_hash(rules_doc: dict) -> str:
    canonical = json.dumps(rules_doc, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def load_baby_rules_snapshot() -> dict:
    """현재 규칙 파일 내용 + 버전 + 해시를 얼린다(R6).

    호출자(P1/P5)는 리비전 생성/재바인딩 시점에 이 스냅샷을 **한 번** 만들어
    `planning.plan_revision.domain_snapshot` 같은 불변 저장소에 같이 넣어 두고,
    그 뒤로는 그 리비전에 대한 모든 build_baby_requirements() 호출에 이 스냅샷을
    (domain_snapshot["baby_rules_snapshot"]로) 다시 넘겨야 한다. 그래야
    config/baby_requirement_rules.yaml 이 나중에 바뀌어도 이미 계산된 리비전은
    항상 같은 결과를 재현한다 — PlanRepo._domain_snapshot() 이 config.domain 의
    definition/content_hash 를 얼리는 것과 동일한 패턴.
    """
    rules_doc = _load_rules()
    return {
        "rule_set_version": rules_doc["rule_set_version"],
        "rule_set_hash": _rule_set_hash(rules_doc),
        "rules_doc": rules_doc,
    }


def _req_id(revision_id: str, rule_key: str, suffix: str = "") -> str:
    return str(uuid5(NAMESPACE_URL, f"truefit:requirement:{revision_id}:{rule_key}{suffix}"))


def _timing_for_born(age_months: int, window: dict) -> str:
    min_m = window.get("min_months") or 0
    if age_months < min_m:
        return "later"
    return "now"


def _timing_for_prenatal(reference_date: str, due_date: str | None) -> str:
    if not due_date:
        return "later"
    from datetime import date

    ref = date.fromisoformat(reference_date)
    due = date.fromisoformat(due_date)
    days = (due - ref).days
    if days <= 0:
        return "now"
    if days <= 60:
        return "soon"
    return "later"


def build_baby_requirements(conditions: dict, domain_snapshot: dict) -> list["BabyRequirement"]:
    """정규화된 조건 + 도메인 스냅샷 → 안정적으로 정렬된 BabyRequirement 목록(슬롯당 1개).

    conditions 는 `normalize_baby_conditions()` 의 NormalizedConditions 형태를
    기대한다: category='baby', mode, age_stage={"months":int,"exact":bool}(born)
    또는 due_date(prenatal), needs[], owned_items[], independent_sitting(선택) —
    그리고 호출자가 채워 넣는 revision_id. 예전에 최상위 age_months 를 읽던 것은
    실제 P1 산출물과 어긋나는 버그였다(R3) — age_stage.months 만 신뢰한다.
    domain_snapshot 은 날짜 의존 계산에 쓸 reference_date 를 반드시 담아야
    한다(§CONTRACTS "no unrecorded current-date effect") — 없으면 실패한다.
    domain_snapshot["baby_rules_snapshot"] (load_baby_rules_snapshot() 의 결과)이
    있으면 그 얼린 규칙 내용을 쓴다(R6) — 없으면 현재 파일을 그대로 읽되
    결과의 매 constraints 에 rule_set_pinned=False 로 표시해 "이 결과는 실행
    시점의 파일에 묶여 있다"는 사실을 감춘 채 호출자가 오해하지 않게 한다.

    v3(develop `da79839` 정렬): 순수 함수라 DB를 모른다 — 보유 여부는 라벨
    수준(`owned=[{"label":...,"qty":...,"unit_code":...}]`)까지만 계산하고,
    실제 plan_condition UUID 연결은 persist_baby_requirements()(DB 연산)가
    채운다. 더 이상 "보유 조각 + 잔여 조각" 두 개로 쪼개지 않는다 — 슬롯당
    항상 정확히 하나의 BabyRequirement(총 required_qty + fulfilled_qty)다.
    """
    pinned_snapshot = domain_snapshot.get("baby_rules_snapshot")
    if pinned_snapshot is not None:
        rules_doc = pinned_snapshot["rules_doc"]
        rule_set_hash = pinned_snapshot["rule_set_hash"]
        rule_set_pinned = True
    else:
        rules_doc = _load_rules()
        rule_set_hash = _rule_set_hash(rules_doc)
        rule_set_pinned = False

    reference_date = domain_snapshot.get("reference_date")
    if not reference_date:
        raise RequirementRuleError("domain_snapshot.reference_date 없음 — 날짜 의존 계산 불가")

    revision_id = str(conditions.get("revision_id") or "")
    mode = conditions.get("mode")
    needs = set(conditions.get("needs") or [])
    owned = set(conditions.get("owned_items") or [])
    age_stage = conditions.get("age_stage") or {}
    age_months = age_stage.get("months")
    age_exact = age_stage.get("exact")
    due_date = conditions.get("due_date")
    independent_sitting = conditions.get("independent_sitting")
    owned_slot_map = rules_doc.get("owned_item_slot_map") or {}

    predicate_values = {
        "independent_sitting": independent_sitting,
    }

    out: list[BabyRequirement] = []
    for rule in rules_doc["rules"]:
        if not needs & set(rule["needs"]):
            continue
        if mode not in rule["mode"]:
            continue

        data_gap = bool(rule.get("data_gap"))
        window = rule.get("age_window") or {}
        if mode == "born":
            if age_months is None:
                raise RequirementRuleError(
                    f"{rule['rule_key']}: mode=born 인데 age_stage.months 없음")
            timing = _timing_for_born(age_months, window)
        else:
            timing = _timing_for_prenatal(reference_date, due_date)

        constraints: dict = {"rule_key": rule["rule_key"], "source_kind": rule["source_kind"],
                              "review_status": rule["review_status"],
                              "rule_set_version": rules_doc["rule_set_version"],
                              "rule_set_hash": rule_set_hash, "rule_set_pinned": rule_set_pinned}
        if mode == "born":
            constraints["age_months"] = age_months
            constraints["age_exact"] = age_exact
        if data_gap:
            constraints["data_gap"] = True
            constraints["data_gap_reason"] = rule.get("data_gap_reason")
        for predicate, required in (rule.get("applicability") or {}).items():
            constraints[f"requires_{predicate}"] = required
            constraints[f"actual_{predicate}"] = predicate_values.get(predicate)

        slot_key = rule["slot_key"]
        required_qty = float(rule["required_qty"])
        owned_label = next((label for label, slot in owned_slot_map.items()
                            if slot == slot_key and label in owned), None)

        owned_entries: list[dict] = []
        fulfilled_qty = 0.0
        if owned_label and required_qty > 0:
            owned_qty = min(1.0, required_qty)
            owned_entries = [{"label": owned_label, "qty": owned_qty, "unit_code": rule["unit_code"]}]
            fulfilled_qty = owned_qty

        out.append(BabyRequirement(
            id=_req_id(revision_id, rule["rule_key"]),
            revision_id=revision_id, slot_key=slot_key, group_key=slot_key,
            required_qty=required_qty, unit_code=rule["unit_code"], mandatory=rule["mandatory"],
            timing=timing, constraints=constraints, owned=owned_entries, fulfilled_qty=fulfilled_qty,
        ))

    out.sort(key=lambda r: (_TIMING_RANK.get(r.timing, 9), 0 if r.mandatory else 1, r.slot_key))
    return out


def persist_baby_requirements(conn, revision_id, requirements: list[BabyRequirement]
                              ) -> list[BabyRequirement]:
    """build_baby_requirements() 의 순수 결과를 실제 planning.plan_node/requirement
    행(진짜 UUID)으로 옮기는 별도 저장소 연산(§CONTRACTS IMPLEMENTATION 5;
    DEVELOP_DB_TRANSITION.md "Domain, requirements, ownership" — v3).

    develop 스키마에는 planning.item 이 없다 — 보유 출처는 이 리비전의 실제
    plan_condition(owned_items) 행 UUID로만 표시하고 별도 "보유 item" 행을
    새로 만들지 않는다. 보유 표시 ID는 `owned:<requirement UUID>:<condition
    UUID>` 로 파생하며 DB FK가 아니다(BasketItem.item_id 용, stage4_optimize).

    슬롯마다 ensure_node(template_key=slot_key) 뒤 ensure_requirement 로
    requirement 1개를 보장하고 quantity/unit_code/required + match_spec을
    한 번에 갱신한다. 같은 revision_id/slot_key 재호출은 같은 실제 UUID를
    재사용한다(멱등). 조건에서 보유를 빼고 다시 부르면 owned=[]/fulfilled_qty=0
    으로 실제 행도 같이 갱신된다(보유 해제 반영).
    """
    from src.repo.plan_repo import PlanRepo

    repo = PlanRepo(conn)
    if len({r.id for r in requirements}) != len(requirements):
        raise ValueError("duplicate_requirement_id")

    owned_condition_id: UUID | None = None
    if any(r.owned for r in requirements):
        owned_condition_id = repo.active_condition_id(revision_id, "owned_items")
        if owned_condition_id is None:
            raise ValueError("owned_items_condition_not_found_for_revision")

    out: list[BabyRequirement] = []
    for r in requirements:
        if not math.isfinite(r.required_qty) or r.required_qty < 0:
            raise ValueError(f"invalid_required_qty:{r.slot_key}")

        owned_with_source = []
        fulfilled_qty = 0.0
        for entry in r.owned:
            qty = entry.get("qty", 0)
            unit_code = entry.get("unit_code", r.unit_code)
            if not math.isfinite(qty) or qty < 0:
                raise ValueError(f"invalid_owned_qty:{r.slot_key}")
            if unit_code != r.unit_code:
                raise ValueError(f"owned_unit_mismatch:{r.slot_key}")
            source_condition_id = entry.get("source_condition_id")
            if source_condition_id is not None and str(source_condition_id) != str(owned_condition_id):
                # Either stale (superseded) or from a different revision — never trusted.
                raise ValueError(f"cross_revision_condition_rejected:{r.slot_key}")
            owned_with_source.append({**entry, "unit_code": unit_code,
                                      "source_condition_id": str(owned_condition_id)})
            fulfilled_qty += qty
        fulfilled_qty = min(fulfilled_qty, r.required_qty)

        node_id = repo.ensure_node(revision_id, r.slot_key, r.slot_key)
        requirement_id = repo.ensure_requirement(revision_id, node_id, {})
        persisted = r.model_copy(update={
            "id": str(requirement_id), "revision_id": str(revision_id),
            "owned": owned_with_source, "fulfilled_qty": fulfilled_qty,
        })
        match_spec = {"schema_version": 3, "baby_requirement": persisted.model_dump(mode="json")}
        repo.set_requirement_totals(
            requirement_id, quantity=r.required_qty, unit_code=r.unit_code,
            required=r.mandatory, match_spec=match_spec,
        )
        out.append(persisted)
    return out


def load_persisted_baby_requirements(conn, revision_id) -> list[BabyRequirement]:
    """Reload the same v3 boundary, including exact owned coverage — ordered by the
    owning plan_node's position/template_key (planning.requirement itself has
    neither column; slot_key/position live on plan_node, joined here)."""
    from src.repo.plan_repo import PlanRepo
    rows = PlanRepo(conn)._all(
        "SELECT req.match_spec FROM planning.requirement req "
        "JOIN planning.plan_node n ON n.id = req.node_id "
        "WHERE req.revision_id=%s AND req.status='active' ORDER BY n.position, n.template_key",
        (revision_id,),
    )
    return [BabyRequirement.model_validate(row["match_spec"]["baby_requirement"])
            for row in rows if "baby_requirement" in (row["match_spec"] or {})]


# TODO: 실제 룩업 테이블로 교체 (data/game_requirements.csv, balance_profiles 등)
_GAME_TIER = {  # (해상도) → (gpu_tier_min, cpu_tier_min, ram_gb, vram_gb)
    "FHD_144": (6, 6, 16, 8),
    "QHD_165": (7, 5, 16, 12),
    "4K": (9, 5, 32, 16),
}
_PSU_K = 1.5


def _computer_build(slots: Slots, log: LogFn) -> RequirementSpec:
    res = slots.values.get("resolution", "FHD_144")
    gpu_t, cpu_t, ram_gb, vram = _GAME_TIER.get(res, _GAME_TIER["FHD_144"])
    brand = slots.values.get("brand_pref", "none")
    socket_in = {"intel": ["LGA1851"], "amd": ["AM5"], "none": ["LGA1851", "AM5"]}[brand]

    # PSU 헤드룸: (cpu_tdp + gpu_tgp + 표준부하) * K → 표준 용량
    est_cpu_tdp, est_gpu_tgp = 125, 300  # TODO: 실제 후보 스펙에서
    required_w = int((est_cpu_tdp + est_gpu_tgp + 75) * _PSU_K)
    wattage_min = next(w for w in (550, 650, 750, 850, 1000, 1200) if w >= required_w)

    targets = {
        "CPU": {"perf_tier_min": cpu_t, "socket_in": socket_in, "tdp_budget_w": est_cpu_tdp},
        "GPU": {"perf_tier_min": gpu_t, "vram_gb_min": vram, "tgp_budget_w": est_gpu_tgp},
        "RAM": {"type": "DDR5", "capacity_gb_min": ram_gb},
        "메인보드": {"socket_in": socket_in, "form_in": ["ATX", "mATX"], "mem_type": "DDR5"},
        "저장장치": {"interface": "NVMe", "capacity_gb_min": 1000},
        "파워": {"wattage_min": wattage_min, "plus_rating_min": "Gold"},
        "케이스": {"form": "ATX_mid"},          # 데모 고정
        "쿨러": {"tdp_capacity_w_min": est_cpu_tdp},
    }
    link_rules = [
        "cpu.socket == mainboard.socket",
        "ram.type == mainboard.mem_type",
        "gpu.length_mm <= case.max_gpu_len_mm",
        "cooler.height_mm <= case.max_cooler_height_mm",
        "sum(power) <= psu.wattage * 0.9",
    ]
    budget_total = slots.values.get("budget_max") or 0
    alloc = {"GPU": 0.40, "CPU": 0.18, "메인보드": 0.10, "RAM": 0.08,
             "저장장치": 0.07, "파워": 0.08, "케이스": 0.05, "쿨러": 0.04}
    feasibility = "ok"  # TODO: est_total vs budget 예비 판정

    flags = []
    if "resolution" in slots.assumed_keys:
        flags.append("resolution_assumed")

    log(f"      게임 요구: GPU tier≥{gpu_t}, CPU tier≥{cpu_t}, RAM {ram_gb}GB, VRAM {vram}GB")
    log(f"      PSU 헤드룸: 필요 {required_w}W → 최소 {wattage_min}W (K={_PSU_K})")
    log(f"      link_rules {len(link_rules)}개 기록 · 예산배분 가이드 · feasibility={feasibility}")

    return RequirementSpec(
        list_id=str(uuid.uuid4()),
        category="computer",
        mode=slots.mode,
        targets=targets,
        link_rules=link_rules,
        budget={"total": budget_total, "alloc": alloc, "feasibility": feasibility},
        flags=flags,
    )


def run(slots: Slots, cat_def: dict, log: LogFn) -> RequirementSpec:
    log("[2] 요구사양 빌드 ...")
    if slots.category == "computer":
        return _computer_build(slots, log)
    # TODO: 유아 요구사양 빌드 (월령 → age_fit_table → 카테고리·시점)
    raise NotImplementedError("stage2: 유아 요구사양 빌드 미구현 (데이터 확보 후)")
