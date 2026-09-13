"""Truefit 파이프라인 진입점 (콘솔).

실행:
    python main.py                      # 기본 시나리오 (computer_pass)
    python main.py computer_research    # 재탐색 1회 후 통과
    python main.py --list               # 시나리오 목록

MOCK_MODE(기본 켜짐)에서는 LLM·임베딩을 호출하지 않고 고정 가짜 데이터로 흐름만 보여준다.
[3-C] 적대적 검증은 시나리오 파일의 정답값을 주입한다 (실제 탐지 성능 아님).

웹 API 로 같은 흐름을 보려면:  uvicorn src.api:app --reload
"""
from __future__ import annotations

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from src.config import APP_NAME, SCENARIO_DIR
from src.pipeline import run_pipeline

_DEFAULT_SCENARIO = "computer_pass"


def _print_result_table(result) -> None:
    b = result.build
    v = result.verification.targets[0] if result.verification and result.verification.targets else None
    e = result.explanation
    print("\n" + "=" * 78)
    print(f"[결과] {APP_NAME} 견적 — {result.input_text}")
    print("-" * 78)
    print(f"{'슬롯':<10}{'부품':<44}{'가격':>12}{'tier':>6}")
    print("-" * 78)
    for it in b.items:
        print(f"{it.slot:<10}{it.name[:42]:<44}{it.price:>12,}{it.perf_tier:>6.0f}")
    print("-" * 78)
    print(f"{'총액':<10}{'':<44}{b.totals.get('price', 0):>12,}")
    if v:
        print(f"세트 신뢰도 {v.confidence}  ·  검증 라운드 {v.rounds}  ·  통과={v.passed}"
              + (f"  ·  회색축 {v.gray_axes}" if v.gray_axes else ""))
    if e:
        print(f"기여도  가격 {e.contribution.get('가격')}%  성능 {e.contribution.get('성능')}%  "
              f"호환성 {e.contribution.get('호환성')}%")
        print(f"설명    {e.headline}")
        for c in e.caveats:
            print(f"  주의  {c}")
        if e.review_line_by_slot:
            print("리뷰 관측 (상품 단위 · 점수 아님)")
            for slot, line in e.review_line_by_slot.items():
                print(f"  {slot:<8} {line}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] in ("--list", "-l"):
        print("사용 가능한 시나리오:")
        for p in sorted(SCENARIO_DIR.glob("*.json")):
            print(f"  - {p.stem}")
        sys.exit(0)

    scenario = args[0] if args else _DEFAULT_SCENARIO

    print("=" * 78)
    print(f"{APP_NAME} 목적성 쇼핑 파이프라인  |  시나리오: {scenario}")
    print("=" * 78)

    result = run_pipeline(scenario, on_log=print)
    _print_result_table(result)
