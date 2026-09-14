# P5 develop 전환 결과 검토 — 2026-09-14

## 결론

**P5 partial 유지. 다음 통합 단계인 P7로 완료 인계할 수 없다.** P6는 P5가 아닌 P1에 의존하므로 기존 P0/P1 조건 아래 독립 진행할 수 있다. P7의 저장 구조 준비는 가능하지만 유아 추천→편집→확정 연결 완료는 보류한다.

기준: HEAD `110f6ca` + 현재 미커밋 변경, [P5 보고서](P5.md)의 최신 v3 절, [P5 ACTIVE DB CONTRACT](../P5_recommendation_http.md). 기존 테스트는 재실행하지 않고 코드·보고서를 대조했다. DB/서비스에는 적용하지 않았다.

## 보고서에 기반한 인정 범위

최신 보고서는 문법 검사1건, 필요량/최적화 테스트44 passed/11 skipped만 제시한다. D5 DB/HTTP 사례는 모두 미측정임을 명시한다. 과거274건 및 RH01~RH06 HTTP 실적은 이전 DB 구조의 결과이므로 새 구조의 통합 증거로 사용하지 않는 구분은 적절하다.

start_recommendation의 baby501 고정 차단을 제거하고 실제 필요량 저장→run snapshot 생성 경로를 추가했으며, 백그라운드에서 candidate.selected/qty/timing에 결과를 쓰는 변경은 확인했다. 그러나 이것만으로 실제202→결과 재조회가 동작한다고 승인할 수 없다.

## 완료 차단 문제

### R1 — 결과 재조회 adapter가 삭제된 DTO/저장소에 의존

`src/services/recommendation_service.py:_load_baby_basket_items`는 `r.fulfilled_by_item_id`를 읽고 `prepo.list_items_with_product`를 호출한다. 현재 BabyRequirement에는 해당 속성이 없고 PlanRepo에도 메서드가 없다. 비어 있지 않은 requirements에서는 속성 접근부터 실패할 수 있고, 빈 목록이어도 저장소 호출은 성립하지 않는다. 보고서가 인정한 “planning.item adapter 미전환”은 단순 미검증이 아닌 실제 코드 불일치다.

수정: requirement/node + 현재 run의 candidate 상태 및 owned[]/fulfilled_qty에서 BasketItem을 재구성한다. GET은 저장 결과만 읽고 근거는 현재 권한/유효성만 재확인한다. 실제 develop DB에서202→종료→GET 반복 성공과 동일 식별자·합계를 검증한다.

### R2 — 유아 item_id/교체 방식이 v3 계약과 다름

`_require_candidate_item`은 PC와 유아 모두 item_id를 candidate UUID로 해석한다. v3 유아 계약은 requirement UUID를 안정 item_id로 사용하고 현재 run의 선택 후보를 찾도록 요구한다. swap_candidate는 기존 candidate의 variant/observation을 다른 후보 값으로 덮어써 기존 검증/근거와 상품의 연결도 어긋날 수 있다.

수정: baby 전용 requirement→현재 candidate adapter를 만들고 슬롯 안 후보 선택 상태를 전환한다. PC candidate 기반 계약은 보존한다. 기존 후보의 검증 근거를 새 상품의 근거로 재사용하지 않는다. 교체 후 동일 baby item_id·변경 candidate_id, 올바른 검증/근거, 슬롯당 선택 하나를 확인한다.

### R3 — 현재 run 제한·동시 편집 원자성·선택 재검증 미충족

`_require_candidate_item`은 run.revision_id 일치만 확인하고 현재 run인지 검사하지 않는다. update_item/swap_candidate는 잠금 없는 revision 조회값과 If-Match를 비교한 뒤 수정한다. bump_lock_version은 expected version 조건 없이 증가하므로 같은 버전을 읽은 두 요청이 모두 통과할 수 있다.

update_item은 selected=true를 저장하기 전에 P3 eligibility 확인을 수행하지 않는다. 결과 조립 중 재계산으로 표시만 조정하는 것으로 저장 상태 검증을 대신할 수 없다. 보고서도 실제 동시409/rollback을 아직 검증하지 않았다.

수정: revision row lock 또는 expected-version 조건부 UPDATE를 포함한 단일 트랜잭션에서 현재 run/requirement/후보/관측값 범위→P3 선택 가능 여부→P4 재계산→저장·버전 증가를 수행한다. 이전 run 후보 편집 거부, 같은 If-Match의 동시 요청 중 하나만 성공, 실패 후 candidate/event/version 부분 변경 없음 등을 확인한다.

### R4 — 저장한 시작 snapshot을 실제 실행에서 사용하지 않음

start_recommendation은 normalized_conditions/domain_snapshot/requirement_ids를 snapshot에 넣지만 execute_recommendation은 `prepo.load_full(revision_id)`로 현재 조건을 다시 읽어 category와 values를 선택한다. `_execute_baby_recommendation`도 현재 active requirements를 재조회한다. 시작 시 고정된 입력과 다른 조건/필요량으로 실행될 수 있다. `_baby_domain_snapshot`은 현재 규칙 파일을 읽으며 선택된 config.domain_version의 definition/content_hash를 고정했다는 보장도 없다.

수정: 시작 트랜잭션에서 규칙 버전·조건·필요량을 일관되게 고정하고 worker는 해당 run.input_snapshot을 사용한다. 카테고리 분기도 저장된 입력을 따른다. 조건 변경 시 결과 게시를 stale로 종료하는 동작과 별개로 계산 자체의 재현성을 보장한다. 실행 지연 중 조건/규칙 변경 사례에서 입력 불변 및 stale 상태 지속을 검증한다. 중복 실행 방지·중단 run 회수도 기존 지시의 남은 조건으로 기록한다.

## P5 완료에 필요한 최소 새 증거

- 전용 develop DB에서 유아 생성→조건→202→실제 종료→반복 GET. 정상 추천이 불가능한 데이터라면 이유 있는 비충족 결과로 종료해도 해당 경계는 검증 가능.
- 수량/시점/담기·빼기·교체 후 저장 상태와 화면 재조회 일치, baby item_id 안정성.
- 교차 사용자·교차 run·위조 후보 거부, 동시 If-Match409 및 실패 rollback.
- 시작 snapshot 불변·stale 처리·실패 상태 지속, 변경 영향이 있는 PC 상호작용 회귀.
- P3-D3-02가 blocked인 동안 실제 외부 검색을 포함한 정상 유아 추천 완료는 별도 보류. HTTP 실패/미설정 처리까지 검증을 중단할 이유는 아니다.

기존 순수 계산 테스트를 반복하는 대신 위 미측정 D5 경계를 검증한다. 브라우저 실행 실적도 기존 RH07 지시대로 별도 확인하며 HTTP 단독 통과로 대체하지 않는다.

## 다음 단계 진행 범위

| 단계 | 판단 |
|---|---|
| P6 | P5와 독립. P1 소유권/조건 계약 및 P0 선행 게이트 아래 진행 가능 |
| P7 | purchase_line/snapshot 저장 준비는 가능. P5 출력·편집 계약이 불완전하므로 실제 유아 확정 흐름 완료 인계 불가 |
| P8 | 후기 독립 구현은 기존 P0/P6 조건 아래 가능. 추천/확정 이벤트 통합 검증은 P5/P7 이후 |
| P9 | 운영 준비 완료 보류. 서비스 DB 적용 전 실제 사용자 흐름과 외부 검색 검증 필요 |

현재 보류 이유는 보고서의 상태명이 partial이기 때문이 아니라 R1~R4의 구현 누락과 D5 실측 부재다. P0~P4의 미충족 게이트도 별도로 남아 있으며 이번 P5 변경으로 자동 해소되지 않는다.
