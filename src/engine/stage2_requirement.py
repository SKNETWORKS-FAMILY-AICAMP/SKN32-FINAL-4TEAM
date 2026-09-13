"""[2] 요구사양 빌드.

슬롯(사용자 언어) → 기계 판정 가능한 목표사양(RequirementSpec).
100% 규칙·룩업. LLM은 extra 자유조건 파싱 / 업그레이드 현재구성 파싱에만 (데모 생략).
컴퓨터: game_requirements + perf_tier 사다리 + PSU 헤드룸 공식 + link_rules 기록.
유아: 월령 → age_fit_table → 필요 카테고리·시점.

build_baby_requirements(conditions, domain_snapshot) 은 [2]의 유아 경로 — P0 v3
planning.requirement(slot_key/group_key/fulfilled_by_item_id) 경계에 맞춘 순수
함수다. config/baby_requirement_rules.yaml (버전 있는 데이터, 코드 아님) 을 읽어
정규화된 conditions 를 list[BabyRequirement] 로 변환한다. DB에 아무것도 쓰지
않는다. persist_baby_requirements() 가 이 결과를 실제 planning.requirement/
planning.item 행(진짜 UUID)으로 옮기는 별도 저장소 연산이다(§CONTRACTS
IMPLEMENTATION 5 — "Persist owned rows ... through a separate repository
operation; pure rule function emits plan changes").

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
import uuid
from functools import lru_cache
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

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
    """정규화된 조건 + 도메인 스냅샷 → 안정적으로 정렬된 BabyRequirement 목록.

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

        if owned_label and required_qty > 0:
            fulfilled_id = f"owned:{owned_label}"
            owned_qty = min(1.0, required_qty)
            out.append(BabyRequirement(
                id=_req_id(revision_id, rule["rule_key"], ":owned"),
                revision_id=revision_id, slot_key=slot_key, group_key=slot_key,
                required_qty=owned_qty, unit_code=rule["unit_code"], mandatory=rule["mandatory"],
                timing=timing, constraints={**constraints, "owned": True},
                fulfilled_by_item_id=fulfilled_id,
            ))
            remaining = required_qty - owned_qty
            if remaining > 0:
                out.append(BabyRequirement(
                    id=_req_id(revision_id, rule["rule_key"], ":remaining"),
                    revision_id=revision_id, slot_key=slot_key, group_key=slot_key,
                    required_qty=remaining, unit_code=rule["unit_code"], mandatory=rule["mandatory"],
                    timing=timing, constraints=constraints, fulfilled_by_item_id=None,
                ))
        else:
            out.append(BabyRequirement(
                id=_req_id(revision_id, rule["rule_key"]),
                revision_id=revision_id, slot_key=slot_key, group_key=slot_key,
                required_qty=required_qty, unit_code=rule["unit_code"], mandatory=rule["mandatory"],
                timing=timing, constraints=constraints, fulfilled_by_item_id=None,
            ))

    out.sort(key=lambda r: (_TIMING_RANK.get(r.timing, 9), 0 if r.mandatory else 1, r.slot_key))
    return out


def persist_baby_requirements(conn, revision_id, requirements: list[BabyRequirement]
                              ) -> list[BabyRequirement]:
    """build_baby_requirements() 의 순수 결과를 실제 planning.requirement/planning.item
    행(진짜 UUID)으로 옮기는 별도 저장소 연산(§CONTRACTS IMPLEMENTATION 5, R5 수정).

    `owned:<라벨>` 같은 합성 마커는 여기서 끝난다 — 반환되는 BabyRequirement.id 와
    fulfilled_by_item_id 는 항상 실제 planning.requirement.id / planning.item.id 다.
    planning.requirement 는 (revision_id, slot_key) 당 한 행이므로(PlanRepo.ensure_requirement),
    같은 slot_key 로 나뉜 조각(예: 보유 몫 + 남은 몫)은 총량/fulfilled_qty를 가진 하나의 DTO와 행으로 합쳐 저장하고
    match_spec 에 조각별 상세를 남긴다 — 이중 계산 없음. 재호출해도 기존 owned
    item 행을 재사용한다(멱등, rule_key 로 찾음).
    """
    from src.repo.plan_repo import PlanRepo

    repo = PlanRepo(conn)
    by_slot: dict[str, list[BabyRequirement]] = {}
    for r in requirements:
        by_slot.setdefault(r.slot_key, []).append(r)

    out: list[BabyRequirement] = []
    for slot_key, pieces in by_slot.items():
        if len({p.unit_code for p in pieces}) != 1 or len({p.timing for p in pieces}) != 1:
            raise ValueError("incompatible_requirement_pieces")
        group_key = pieces[0].group_key or slot_key
        mandatory = any(p.mandatory for p in pieces)
        timing = min((p.timing for p in pieces), key=lambda t: _TIMING_RANK.get(t, 9))
        unit_code = pieces[0].unit_code
        match_spec = {
            "unit_code": unit_code,
            "pieces": [
                {"required_qty": p.required_qty, "mandatory": p.mandatory, "timing": p.timing,
                 "constraints": p.constraints, "owned": bool(p.fulfilled_by_item_id)}
                for p in pieces
            ],
        }
        requirement_id = repo.ensure_requirement(revision_id, slot_key, match_spec,
                                                 group_key=group_key)

        fulfilled_by_item_id = None
        for p in pieces:
            if p.fulfilled_by_item_id and p.fulfilled_by_item_id.startswith("owned:"):
                label = p.fulfilled_by_item_id.split(":", 1)[1]
                rule_key = p.constraints.get("rule_key", slot_key)
                item_id = _find_or_create_owned_item(
                    repo, revision_id, label=label, slot_key=slot_key, rule_key=rule_key,
                    qty=p.required_qty, unit_code=p.unit_code)
                fulfilled_by_item_id = str(item_id)
            elif p.fulfilled_by_item_id:
                existing = repo._one(
                    "SELECT id FROM planning.item WHERE id=%s AND revision_id=%s AND status='owned'",
                    (p.fulfilled_by_item_id, revision_id),
                )
                if existing is None:
                    raise ValueError("invalid_owned_item_reference")
                fulfilled_by_item_id = str(existing["id"])
        total_qty = sum(p.required_qty for p in pieces)
        owned_qty = sum(p.required_qty if p.fulfilled_qty is None else p.fulfilled_qty for p in pieces if p.fulfilled_by_item_id)
        # One persistent requirement per slot, with total demand and explicit owned coverage.
        consolidated = pieces[0].model_copy(update={
            "id": str(requirement_id), "revision_id": str(revision_id),
            "required_qty": total_qty, "mandatory": mandatory, "timing": timing,
            "fulfilled_by_item_id": fulfilled_by_item_id, "fulfilled_qty": owned_qty,
        })
        from psycopg.types.json import Jsonb
        match_spec["baby_requirement"] = consolidated.model_dump(mode="json")
        repo._exec(
            """UPDATE planning.requirement SET fulfilled_by_item_id=%s, quantity=%s,
               unit_code=%s, required=%s, match_spec=%s WHERE id=%s""",
            (fulfilled_by_item_id, total_qty, unit_code, mandatory, Jsonb(match_spec), requirement_id),
        )
        out.append(consolidated)
    return out


def load_persisted_baby_requirements(conn, revision_id) -> list[BabyRequirement]:
    """Reload the same consolidated boundary, including exact owned coverage."""
    from src.repo.plan_repo import PlanRepo
    rows = PlanRepo(conn)._all(
        "SELECT match_spec FROM planning.requirement WHERE revision_id=%s AND status='active' ORDER BY position,slot_key",
        (revision_id,),
    )
    return [BabyRequirement.model_validate(row["match_spec"]["baby_requirement"])
            for row in rows if "baby_requirement" in row["match_spec"]]


def _find_or_create_owned_item(repo, revision_id, *, label: str, slot_key: str, rule_key: str,
                               qty: float, unit_code: str):
    existing = repo._one(
        """SELECT id FROM planning.item
        WHERE revision_id=%s AND status='owned' AND item_spec->>'source_rule_key'=%s""",
        (revision_id, rule_key),
    )
    if existing is not None:
        return existing["id"]
    from psycopg.types.json import Jsonb

    row = repo._one(
        """INSERT INTO planning.item (revision_id, status, qty, unit_code, item_spec)
        VALUES (%s, 'owned', %s, %s, %s) RETURNING id""",
        (revision_id, qty, unit_code,
         Jsonb({"label": label, "slot_key": slot_key, "source_rule_key": rule_key})),
    )
    return row["id"]


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
