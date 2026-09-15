# P2 develop 전환 결과 검토 — 2026-09-14

## 판정

**P2 partial 유지. P3의 검색 provider/검증 규칙 및 P4의 순수 계산 구현은 진행 가능하지만 P2 완료를 전제로 한 DB 통합 승인은 보류한다.** 기본 저장 전환은 재사용하고 아래 경계를 보완한다.

기준: HEAD `110f6ca`, [P2 최신 v3 보고서](P2.md), [P2 ACTIVE DB CONTRACT](../P2_catalog_requirements.md), [공통 전환 계약](../DEVELOP_DB_TRANSITION.md). 현재 작업 트리는 검토 시작 시 깨끗했다. 보고서의 기존 테스트를 재실행하지 않고 소스·테스트 내용을 대조했다. 다음 결함은 정적 검토 결과이며 이번에 동적 재현했다고 주장하지 않는다.

## 인정하는 성과

- planning.item 의존을 제거하고 plan_node→requirement로 저장하는 경로, 실제 requirement UUID 재사용, owned[]/fulfilled_qty DTO 전환을 확인했다.
- 보고서의 카탈로그/필요량32건, 관련 계산/DB 회귀42건 통과 실적을 해당 검증 범위에서 인정한다.
- 젖병2개 필요/1개 보유, 저장·재조회·순차 재실행, 보유 해제, 음수/비유한 필요량, 단위 불일치, 다른 revision의 조건 UUID 거부 테스트가 존재한다.
- 유아 추천 HTTP10건의501은 별도 P5 연결 과제다. 이 실패만으로 P2 자체 실패라고 판단하지 않는다. 반대로 전체226 passed/10 failed/30 skipped는 전체 서비스 통과가 아니다.

## 완료 전 보완 사항

### R1 — 보유 출처 UUID만 검사하고 실제 보유 내용을 검증하지 않음

`src/engine/stage2_requirement.py`의 persist_baby_requirements는 `PlanRepo.active_condition_id`로 현재 owned_items 조건 ID만 읽는다. 조건 value의 품목·수량은 읽지 않는다. 입력 owned entry에 source_condition_id가 없으면 현재 조건 ID를 붙이며, 같은 ID이면 전달된 label/qty를 그대로 신뢰한다.

따라서 “없음”이나 다른 물품을 답한 조건 행이 존재해도 호출자가 젖병 보유 entry를 넘기면 저장 경로는 이를 대조하지 않는다. 다른 revision의 ID를 거부하는 현재 테스트는 이 문제를 검사하지 않는다. 공통 계약의 “owned.qty는 검증된 부모 조건에서만 만든다”를 충족하지 않는다.

보완: 활성 조건의 실제 value를 읽고 P1의 정규화 계약에 따라 품목·단위·수량을 검증/도출한다. 원본에 없는 품목, 과장된 보유량, 같은 출처의 중복 사용, 보유 없음, superseded 조건을 거부하는 테스트를 추가한다. 여러 requirement 사이에도 하나의 실제 보유량을 중복 배분하지 않는다.

### R2 — 순차 멱등성은 있지만 동시 생성 직렬화가 없음

persist_baby_requirements는 revision 잠금을 취하지 않는다. ensure_node/ensure_requirement도 SELECT 후 INSERT하며 자체 잠금이 없다. P2 지시서에 명시된 “중복 슬롯 동시 생성은 revision 잠금으로 직렬화”가 빠져 있다. 현재 중복 검사는 DTO.id만 비교하여 서로 다른 ID의 같은 slot_key도 놓친다.

보완: 저장 시작에 revision 존재·편집 가능 상태를 확인하고 row lock으로 직렬화한다. 입력의 revision 일치와 슬롯 중복도 검사한다. 두 DB 연결의 동시 저장 후 슬롯당 하나의 node/requirement와 동일한 최종 결과가 보장되는지 확인한다. DB UNIQUE 위반으로 한 요청이 실패하는 것만으로 정상 멱등 처리를 대신하지 않는다.

### R3 — 필요 영역 삭제 후 이전 requirement가 계속 활성으로 남음

저장 함수는 이번 입력의 requirement만 upsert하고 이전에 저장했으나 이번 계산에서 사라진 유아 슬롯은 제외/비활성 처리하지 않는다. load_persisted_baby_requirements는 모든 active 유아 payload를 다시 읽는다. 예를 들어 외출+수유에서 수유로 바뀌면 이전 외출 필요 품목이 재조회 결과에 남을 수 있다. 현재 “보유 해제” 테스트는 같은 슬롯의 owned=[] 갱신만 검증하므로 이를 포괄하지 않는다.

보완: revision 잠금 하에서 현재 계산 결과와 기존 유아 슬롯을 비교해 없어진 슬롯을 excluded로 전환한다. PC 등 무관한 requirement는 건드리지 않는다. 다시 필요해진 슬롯은 기존 UUID를 유지해 active로 복원한다. 영역 축소→재조회, 결과 빈 목록, 재추가 사례를 검증한다.

### R4 — match_spec의 다른 정보 삭제 및 재조회 식별자 신뢰

persist_baby_requirements는 ensure_requirement(...,{})를 먼저 호출하고 이후 새 match_spec 객체로 덮어쓴다. 공통 계약이 보존하도록 한 기존 match_spec의 다른 키가 사라진다. load_persisted_baby_requirements는 node와 JOIN하지만 SELECT는 req.match_spec뿐이며, 실제 requirement.id/revision_id/node.template_key 대신 JSON 안의 식별자·slot_key를 그대로 반환한다.

보완: 기존 match_spec을 읽고 baby_requirement 키만 갱신한다. 실제 관계 컬럼에서 DTO id/revision_id/slot_key를 복원하고 JSON의 불일치는 거부하거나 권위 있는 DB 값으로 명시적으로 정규화한다. 다른 match_spec 키 보존과 JSON 식별자 불일치 검증을 추가한다.

### R5 — 명시적 보유 수량 입력 계약 미연결

build_baby_requirements는 owned_items를 set으로 변환하고 첫 일치 label에 대해 min(1,required_qty)만 인정한다. 수량·단위가 있는 객체 입력은 지원하지 않으며 여러 개를 보유한 경우도 한 개만 반영한다. 이는 P1 검토 R2와 연결된 P1→P2 경계다.

보완: P1과 typed 보유 입력을 합의하고 기존 문자열은 호환 adapter로 처리한다. “2개 보유→구매0”, 여러 보유 항목, 단위 변환 불가 거부를 HTTP 정규화→build→persist→reload로 확인한다. P1이 입력을 준비하더라도 P2의 set/1개 고정 로직도 함께 바꿔야 한다.

## 보고서 정정 필요

- remaining의 “P0 review R1은 planning.item FK 문제이므로 moot”는 잘못된 참조다. [현재 P0 검토](P0-develop-review-2026-09-14.md) R1은 recommendation_candidate의 교차 revision 참조와 이를 거부하지 않는 테스트 문제다. planning.item 제거로 해소되지 않는다.
- “P1 review R2는 exact=false 유실”도 잘못됐다. [현재 P1 검토](P1-develop-review-2026-09-14.md) R2는 보유품 수량·단위 정규화 누락이다. exact=false 보존 실적은 인정했다.
- 본문의 P0 관련2개 테스트 파일18건과 YAML의 P1 D1 파일까지 포함한3개 파일18건은 명령 범위가 다르다. 실행 기록에 맞춰 일치시킨다. 테스트 개수를 다시 채우기 위해 전체 스위트를 반복하지 않는다.
- P0/P1 미충족 선행 조건과 P2 자체의 R1~R5를 분리해 remaining에 기록한다.

## 다음 단계

| 단계 | 판단 |
|---|---|
| P3 | 외부 provider 경계·자료 적용 규칙 구현은 가능. P0 JSON 무결성과 P2의 실제 필요량/보유량 계약 완료 후 DB 통합 승인 |
| P4 | 순수 예산/수량·시점 계산 수정 가능. P2의 보유량 신뢰·중복·stale requirement 문제를 해결하기 전 실제 장바구니 계산 완료 승인 불가 |
| P5 | 현재501을 정상 추천으로 연결하는 작업은 원래 선행 조건 유지. P2 payload를 완료로 간주한 통합 승인 보류 |
| P6 등 독립 작업 | 기존 P1/P0 의존 조건 아래 계속 진행 가능 |

우선 R1/R5의 입력·출처 계약을 P1과 확정하고, R2/R3의 트랜잭션·최신 집합 관리, R4의 데이터 보존/재조회 adapter를 보완한다. 새 결함 회귀와 영향받는 경로만 검증한다. 서비스 DB 미적용이나 보고서 작성 주체의 승인 대기는 P2 자체의 기술적 결함이 아니며, 위 미충족 구현이 partial 유지의 이유다.
