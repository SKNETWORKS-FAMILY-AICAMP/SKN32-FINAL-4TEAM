# P4 develop 전환 결과 검토 — 2026-09-14

## 판정

**P4 partial 유지. P5의 실행·화면·저장 adapter 구현은 착수 가능하지만 P4 결과를 검증 완료 입력으로 취급한 통합 승인은 보류한다.** 기존 계산 알고리즘을 전면 재작성할 필요는 없다.

검토 대상: HEAD `110f6ca` + 현재 P4/P3 미커밋 변경, [P4 보고서](P4.md)의 2026-09-14 v3 절, [P4 지시서](../P4_basket_optimizer.md). 보고서의 테스트와 JSON 산출물을 읽고 소스와 대조했다. 테스트·DB 설치·통합 probe를 재실행하지 않았다. 아래는 정적 검토 결과다.

## 인정하는 성과

보고서의 optimizer34건, pipeline/smoke5건, 보유량 DB 회귀13건 결과를 해당 범위에서 인정한다. 실제 requirement UUID/fulfilled_qty 전달, 총2·보유1→구매1, unknown 후보 미선택, 서로 다른 requirement의 check와 단위 불일치 제외, 편집 qty99/100 경계 테스트가 존재한다.

[p4-develop-results-2026-09-14.json](artifacts/p4-develop-results-2026-09-14.json)은 후보4개 모두 unknown이며 feasible=false, 최소 비용/부족 예산=null을 실제 기록한다. 이 실적은 미확인 후보를 억지로 선택하지 않는 경계의 증거다. 정상적인 다품목 구매 조합이나 실제 외부 검색 검증 완료의 증거는 아니다. 과거322,000원 feasible 결과는 당시 안전 규칙 기준의 기록이다.

## P4 자체 보완 사항

### R1 — 자동 선택에서 eligibility=pass를 강제하지 않음

stage3b_rank.rank_baby_candidates는 check.selection_allowed와 eligibility를 독립적으로 ScoredCandidate에 복사한다. stage4_optimize.optimize_baby의 mandatory/optional/deferred 후보 필터는 selection_allowed와 price만 본다. CandidateCheck 모델에도 unknown/fail + selection_allowed=true를 금지하는 교차 필드 제약이 없다.

따라서 잘못 조합된 DTO에서 unknown/fail 후보가 자동 선택될 수 있다. recalculate_basket는 eligibility=pass를 요구하므로 자동 계산과 재계산의 규칙도 다르다. 기존 unknown 테스트는 정상적으로 selection_allowed=false인 입력만 사용한다.

수정: 모든 후보 선택 경로에서 eligibility=pass AND selection_allowed=true를 요구한다. P3 생산자 검증과 별개로 P4 경계에서도 모순 입력을 거부한다. unknown/true, fail/true, missing check 및 정상 pass에 대해 자동 선택·재계산 결과가 일치하는지 확인한다.

### R2 — soon/later 생성에는 구매 수량1~99 제한이 빠짐

optimize_baby는 mandatory/optional-now의 풀 구성에 수량 검사를 추가했지만 deferred 루프는 q를 그대로 BasketItem.qty에 넣는다. q=100 또는 소수도 출력될 수 있다. recalculate_basket에서는 동일 행을 invalid_qty로 판정한다.

수정: 시점과 무관하게 실제 구매 팩 수에 같은 범위를 적용한다. 허용 범위를 넘으면 구매 가능한 후보 행인 것처럼 출력하지 말고 이유를 표시한다. now/soon/later 각각99·100·소수 경계와 optimize→recalculate 일치를 확인한다. 기존99/100 테스트는 recalculate 경계만 검사하므로 자동 생성 전체 통과 근거가 아니다.

### R3 — 보유 충족량과 출력된 보유 행 수량이 다를 수 있음

optimize_baby는 잔여 필요량을 r.fulfilled_qty로 계산하지만 출력 행은 r.owned 각 entry.qty를 그대로 사용한다. 둘의 합 일치, entry 단위, source 중복을 검증하지 않는다. 예를 들어 required_qty=2, fulfilled_qty=1, owned.qty=2이면 자동 계산은1개 구매가 필요하다고 보지만, 구매 없이 출력된 owned 행만 recalculate하면2개 충족으로 판단할 수 있다. entry 단위도 r.unit_code로 덮어써 불일치를 숨긴다.

같은 requirement와 source_condition_id의 여러 entry는 동일 item_id를 만들고, 별도 owned_items 입력은 출처 식별 없이 슬롯별 수량만 합산한다. 두 보유 입력 경로를 함께 사용할 때 동일 실제 재고를 다른 requirement에 재사용하지 않는 보장도 없다.

수정: P2/P1과 정규화·배분된 보유량 계약을 확정하고 그 수량으로 계산/출력을 통일한다. 단위 불일치·중복 출처·비유한 수량·fulfilled_qty 불일치를 거부한다. 보유량이 필요량보다 많다면 실제 보유량과 충족에 사용한 양을 구분한다. 동일 출처의 중복 표시 ID를 통합하거나 명시적 고유 키를 정의한다. optimize 결과의 구매 행을 제외하고 재계산해도 보유 충족량이 늘어나지 않는 회귀가 필요하다.

### R4 — 필요 단위와 구매 팩 수의 계약 불일치

현재 optimize는 잔여 required_qty를 그대로 구매 qty로 사용하고 비용도 price*q로 계산한다. recalculate의 충족량 역시 it.qty만 합산한다. unit_qty는 selected_units에만 적용된다. 그러나 ACTIVE D4는 필요량을 qty*unit_qty로 환산하도록 요구한다. 기존 OP04/OP08 테스트의 requirement는 pack 단위이므로 현재 코드에 맞지만 일반적인 개수 필요량 환산을 증명하지 않는다.

수정: requirement가 pack 수인지 each 등 기본 단위 수인지 P2/P4 계약을 명확히 분리한다. 기본 단위 필요량이면 후보별 ceil(잔여량/팩당 해당 단위량)으로 구매 팩 수와 비용을 계산하고 충족량도 같은 단위로 환산한다. pack 요구량이라면 해당 단위의 환산계수는1이며 내용물 개수 통계와 구분한다. 80개 필요/40개입2팩, 일부 보유, 후보별 다른 포장 크기를 검증한다. 단위 모델을 합의하지 않은 채 모든 qty에 unit_qty를 일괄 곱하는 수정은 하지 않는다.

## 증거·범위 보완

- top-N 절단은 이전 보고서부터 미검증 상태다. 현재 alternatives.search는 항상 exact_branch_and_bound이고 bounded_requirements만 별도 표시한다. 절단 발생 시 전체 최적해 보장과 후보군 내부 정확 탐색을 구분하고, 8개 초과 후보에서 표시·최저비용 진단의 범위를 검증한다.
- 보고서의 verify_baby_candidate(None,...) AttributeError는 RagService 객체 자체가 없는 호출이다. 정상 미설정 경로인 RagService(MaterialRepo(conn), None)와 다르므로 이것만으로 현재 provider 미설정 처리 결함을 확정하지 않는다. P3 보고서의 실제 미설정 경로 테스트와 구분한다.
- 전체278 passed/10 failed/2 skipped는 전체 통과가 아니다. 유아 HTTP501은 P5 연결 과제이고 이 실패만으로 P4 알고리즘 결함으로 보지는 않는다.
- 변경 파일 설명의 “9 new D4 tests”와 실행 기록의8건은 맞춰 정리한다. 검토를 위해 전체 테스트를 다시 실행할 필요는 없다.

## 다음 단계

| 단계 | 진행 범위 |
|---|---|
| P5 | 비동기 실행·DTO adapter·저장·미설정/비충족 화면 구현 가능. 위 R1~R4 및 P0/P1/P2/P3 게이트 해결 전 정상 추천 통합 완료는 보류 |
| P7 | purchase_line snapshot 저장 준비 가능. P4의 수량·단위·안전 판정 일관성을 확보한 뒤 확정 검증 연결 |
| P9 | 운영 점검 준비 가능. 실제 외부 검색 및 통합 사용자 흐름 완료는 아직 미승인 |

P0~P3의 개별 검토 결함이 자동 해결됐다고 간주하지 않는다. 우선 P4 자체 R1/R2를 수정하고 P1/P2와 R3/R4 입력 계약을 맞춘다. 새 경계 테스트와 영향받는 계산 경로만 검증한 뒤 P4를 재판정한다.
