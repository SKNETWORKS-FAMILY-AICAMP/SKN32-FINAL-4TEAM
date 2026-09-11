"""[2] 요구사양 빌드.

슬롯(사용자 언어) → 기계 판정 가능한 목표사양(RequirementSpec).
100% 규칙·룩업. LLM은 extra 자유조건 파싱 / 업그레이드 현재구성 파싱에만 (데모 생략).
컴퓨터: game_requirements + perf_tier 사다리 + PSU 헤드룸 공식 + link_rules 기록.
유아: 월령 → age_fit_table → 필요 카테고리·시점.
"""
from __future__ import annotations

import uuid

from src.dto import RequirementSpec, Slots
from src.engine import LogFn

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
