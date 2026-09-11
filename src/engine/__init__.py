"""Truefit 엔진 6단계 (+ [3-0] 후보 수집).

[1] 의도 분해·슬롯필링   → stage1_intent
[2] 요구사양 빌드         → stage2_requirement
[3-0] 후보 수집           → stage3_0_candidates
[3-A] 하드 필터           → stage3a_hardfilter
[3-B] 적합도·병목 순위    → stage3b_rank
[3-C] 적대적 검증         → stage3c_verify   (데모: 시나리오 정답값 주입)
[4] 세트 최적화/예산 배분 → stage4_optimize
[5] 설명 생성             → stage5_explain

각 stage 함수는 이전 DTO + 컨텍스트를 받아 다음 DTO 를 돌려주고, 진행 로그는 log 콜백으로 흘린다.
실제 로직은 아직 목/스텁이며 `# TODO: 실제 로직 구현 필요` 로 표시한다.
"""
from typing import Callable

LogFn = Callable[[str], None]
