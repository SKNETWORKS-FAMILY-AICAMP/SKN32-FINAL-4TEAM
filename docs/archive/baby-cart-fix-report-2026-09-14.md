# 유아용품 장바구니 A~D 수정 결과

작성일: 2026-09-14

## A. 검증 규칙·근거 상태

기본 합성 카탈로그의 필요 품목은 `bottle`, `formula`, `high_chair`, `baby_food`, `crib`,
`sleepwear`, `stroller`, `car_seat`, `bath`, `skincare`, `diaper`, `wipes`, `mat`, `gate`,
`thermometer`이다. 이 중 `stroller`만 `baby_seat_v1` 설명서 규칙과 합성 설명서 자료를
가진다. 나머지는 검토된 적용 규칙 또는 검토 근거가 없으며, `car_seat`에는 별도로 확인된
KC 인증 근거도 없다. `clothing`은 카탈로그 자체가 없는 명시적 data gap이다.

따라서 기저귀·물티슈 또는 다른 미검토 품목을 `pass`나 비적용으로 바꾸지 않았다. 이 상태는
자동 선택과 확정을 계속 차단한다. 실제로 완료 가능한 유아 시나리오를 만들려면 품목별 적용
범위·버전·필수 입력·공식 출처와 확인일을 갖춘 규칙 및 그 규칙을 만족하는 자료를 일반 적재
경로로 제공해야 한다.

## B. 결과 차단 사유

`persist_candidate_check`가 검증 결과를 후보·필요 품목에 연결해 저장한다. 결과 조회는 저장된
검증 행만 읽어 `missing_requirements`에 안정적인 `reason_code`, 사용자 설명, 다음 행동 및
원래 판정 사유를 넣는다. 규칙 부재는 `verification_rule_missing`으로 표시하며, 예산 부족과
구분한다. 빈 장바구니 요약도 성공형 문구 대신 각 필수 품목의 차단 이유를 보인다.

## C. 명시적 없음

유아용품의 빈 배열 저장 계약은 유지했다. `health_skin=[]`은 ‘특이사항 없음’(영어: ‘No health
or skin concerns’), `owned_items=[]`은 ‘없음’(영어: ‘None owned’)으로 표시한다. `None`과
필드 초기화는 계속 미응답 상태다.

## D. 결과 화면·규칙 기반 채팅

결과 요약은 유아용품에서 ‘품목’ 표현을 사용하고, 선택된 품목이 없을 때 차단 사유를 표시한다.
LLM이 비활성인 규칙 경로는 기저귀·물티슈·젖병·유모차·카시트·아기침대·체온계의 담기, 빼기,
수량 변경 요청을 해석한다. 담기 요청은 저장된 검증 차단 사유를 반환하며 상태를 바꾸지 않는다.
서비스의 직접 선택 경로도 유아 후보에 연결된 검증 결과가 모두 `pass`인 경우에만 허용한다.

## 검증

실행:

```bash
UV_CACHE_DIR=/tmp/truefit-uv-cache uv run python -m pytest -q \
  tests/test_result_summary_checks.py tests/test_session_answer_values.py \
  tests/test_baby_optimizer.py
```

결과: 48 passed.

다음 명령은 `DATABASE_URL`이 없는 환경에서 실행되어 24 skipped였다.

```bash
UV_CACHE_DIR=/tmp/truefit-uv-cache uv run python -m pytest -q \
  tests/test_baby_session_http.py tests/test_baby_recommendation_http.py
```

이 환경에는 PostgreSQL 클라이언트도 없어 전용 PostgreSQL, 기본 합성 카탈로그 및 실제 브라우저
전체 흐름은 실행하지 못했다. 그러므로 기저귀 원래 시나리오는 여전히 규칙·근거 부재로 차단되는
것으로 보고하며, 유아용품의 편집·로그인·확정·리포트 전체 통과를 주장하지 않는다.
