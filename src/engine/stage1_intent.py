"""[1] 의도 분해 · 슬롯필링.

자유 대화 → 조건 세트 완성. LLM 역할은 (a) 자유 텍스트 → 슬롯 추출
(b) 명시 안 한 슬롯을 목적(objective)에 맞춰 기본값 제안(assumed + 한 줄 근거).
required_inputs 는 절대 assumed 하지 않고 missing 으로 남긴다.
칩 클릭 → 슬롯은 서버가 직접(여기 없음, API 계층).
"""
from __future__ import annotations

from src.clients.llm_client import call_llm
from src.dto import SlotFillResult, Slots
from src.engine import LogFn

_SYSTEM = (
    "사용자 발화에서 슬롯을 채우세요. 확실한 것만 confirmed 에. "
    "명시 안 한 슬롯은 목적에 맞춰 기본값을 assumed 에 넣고 한 줄 근거를 assumed_reason 에. "
    "required_inputs 는 절대 assumed 금지 → missing 으로."
)


def _fill_slots(scenario: dict, cat_def: dict, log: LogFn) -> SlotFillResult:
    """LLM fill_slots 호출. 데모에서는 시나리오가 정답값(mock_slot_fill)을 주입한다."""
    if "mock_slot_fill" in scenario:
        call_llm("(mock) 슬롯필링", system=_SYSTEM)  # [MOCK] 로그만
        return SlotFillResult.model_validate(scenario["mock_slot_fill"])
    # TODO: 실제 로직 구현 필요 — Converse 스타일 함수 호출 + 스키마 강제, 파싱 실패 1회 재시도
    raise NotImplementedError("stage1: mock_slot_fill 없는 실호출 미구현 (MOCK_MODE=0)")


def run(scenario: dict, cat_def: dict, log: LogFn) -> Slots:
    log("[1] 의도 분해 · 슬롯필링 ...")
    fill = _fill_slots(scenario, cat_def, log)

    values = {**(cat_def.get("defaults") or {}), **fill.assumed, **fill.confirmed}
    slots = Slots(
        category=scenario["category"],
        mode=scenario["mode"],
        objective_text=scenario["input_text"],
        values=values,
        assumed_keys=list(fill.assumed.keys()),
        missing=list(fill.missing),
    )

    log(f"      확정: {fill.confirmed}")
    for k, v in fill.assumed.items():
        log(f"      가정(assumed): {k}={v}  — {fill.assumed_reason.get(k, '근거 없음')}")
    ok = slots.can_recommend(cat_def["required_inputs"])
    log(f"      빠진 정보: {fill.missing} → 추천 {'가능' if ok else '불가 (되묻기 필요)'}")
    if not ok:
        raise RuntimeError(f"required_inputs 미충족: {fill.missing} — [1]로 되돌려 되묻기")
    return slots
