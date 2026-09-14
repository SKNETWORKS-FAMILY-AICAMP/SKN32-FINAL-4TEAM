# P0 develop 전환 결과 검토 — 2026-09-14

## 판정

**P0 partial 유지. 완료 승인 및 선행 작업 완료를 전제로 한 일괄 인계는 보류한다.** P1/P2/P6의 독립적인 전환 구현은 진행할 수 있지만, 아래 P0 결함을 해소하기 전 해당 단계의 통합 완료로 승인하지 않는다. 처음부터 P0를 재작성할 필요는 없다.

기준: 현재 HEAD `d7e6349`, 목표 develop `da79839`, [P0 보고서](P0.md)의 최신 contract_version=3 절과 [P0 ACTIVE DB CONTRACT](../P0_schema_contracts.md). 보고서의 기존 테스트 결과를 재사용하고 현재 소스/테스트와 develop 원본을 읽어 대조했다. 테스트·DB 설치·서비스 DB 적용을 다시 실행하지 않았다. 아래 결함은 소스 및 테스트 내용으로 확인한 것이며 이번에 동적 재현했다고 주장하지 않는다.

## 승인 차단 사항

### R1 — 교차 revision 후보 저장을 허용하는데 거부 검증 통과로 보고됨 (D0-03)

`src/repo/engine_repo.py:28`의 add_candidate는 run의 revision과 requirement의 revision을 비교하지 않고 INSERT한다. develop FK도 각 ID의 존재만 확인한다. `tests/test_p0_list_item_integrity.py:78`의 테스트는 다른 revision의 requirement를 실제로 저장한 뒤 두 revision이 다르다는 사실을 assert한다. 예외·거절·rollback을 검사하지 않는다. 따라서 이 테스트의 통과는 무결성 보장의 증거가 아니다.

수정: 공통 저장소에서 run/revision/requirement/node 및 candidate variant/관측값의 관계를 쓰기 전에 검증한다. start_run도 주어진 domain_version과 revision의 버전 일치를 확인한다. 잘못된 참조 입력은 거절되고 후보/실행 행이 남지 않는 테스트로 교체한다. 조회 API의 소유권 검사만으로 잘못된 저장 허용을 대체하지 않는다.

### R2 — 근거 JSON 구조·존재·범위 검증 미구현 (D0-03)

`src/repo/engine_repo.py:32`의 link_candidate_evidence는 전달된 dict를 그대로 저장하고 evidence_id/claim_key만 추가한다. `:45`의 link_validation_target은 target/evidence_refs만으로 불완전한 issue를 만들며 대상의 run/revision을 검사하지 않는다. `:55`의 link_validation_evidence도 존재·상품 범위·중복 검증 없이 마지막 issue에 추가한다. 최소 필드와 UUID 검증 및 공통 serializer를 구현했다는 근거가 없다.

보고서는 이를 P3로 미뤘지만 P0 ACTIVE DB CONTRACT는 JSON 타입·교차 run·중복·참조 검증을 명시적으로 요구한다. 실제 외부 검색은 P3이지만, 이미 있는 공통 저장소에 잘못된 참조가 저장되지 않게 하는 일은 P0다. 외부 검색이 없어도 전용 DB에 출처/근거/후보 fixture를 만들어 검증할 수 있다.

수정: 공통 typed serializer와 존재/상품·run·revision 범위 검사를 구현하고, 잘못된 타입·필수 필드 누락·미존재 근거·교차 run/상품·중복·부분 저장 거부를 추가 검증한다. 보고서의 D0-03 pass를 수정한다.

### R3 — develop의 가격 알림 API가 빠짐 (D0-02)

보고서는 현재 checkout에 라우트가 없다는 이유로 기존 경로 보존 검증을 제외했다. 그러나 `git show da79839:src/routers/lists.py`에는 `POST /lists/{list_id}/alert`가 실제 있고 list_service.set_alert를 호출한다. 현재 src/routers/lists.py 및 src/services/list_service.py에는 해당 경로/함수가 없다. schema/repo/service의 import 성공은 HTTP 기능 보존이 아니다.

수정: develop 알림 라우트와 list_service 연결을 복원하고 소유권·활성화/비활성화·목표 금액 저장을 실제 DB/HTTP에서 검증한다. 유아 알림 발송 신규 구현과는 별개로 기존 develop 기능을 보존하는 범위다.

### R4 — 확정이 편집한 수량·구매 시점을 무시 (D0-02)

`src/services/list_service.py:33`의 확정 SELECT는 candidate.qty/timing을 읽지 않는다. `:35`는 단가만 합산하고 `:38`은 timing='now', `:39`는 pack_count=1로 저장한다. 사용자가 2개로 편집해도 확정 내역은 1개가 된다. 보고서의 “qty=2로 예산 초과 확인 후 확정 성공”은 올바른 확정 검증을 입증하지 않는다.

수정: 실제 qty/timing을 조회하여 pack_count·line_amount·당시 snapshot·합계에 반영하고 수정된 수량 기준으로 예산을 재검사한다. qty=2, soon/later, 예산 초과 거부, 확정 재조회 일치 사례를 검증한다. 이는 현재 PC 편집→확정 연결의 결함이며 유아 P7 업무로만 미룰 수 없다.

## 게이트별 판단

| 게이트 | 판단 | 근거 |
|---|---|---|
| D0-01 설치·재실행 | 주요 설치 실적 인정, 증거 보완 필요 | 보고서의 설치/재실행/미적용 없음 및38테이블 결과 재사용. 현재 테스트는 일부 유지/삭제 목록과 개수를 검사하며, 전체 체크섬·shared 트리거 UPDATE·리뷰 메타데이터 결과는 충분히 제시되지 않음 |
| D0-02 세션·PC 동작 보존 | 부분 통과 | PC/유아 조건 및 기본 추천/리포트 실적은 인정. R3/R4 미충족 |
| D0-03 무결성 | 미충족 | R1/R2. 올바른 offer/observation FK 거부·확정 멱등·게스트 접근 사례 통과는 별도로 인정 |

보고서의 213 passed / 12 failed / 30 skipped는 전체 통과가 아니다. 12건 중 유아 requirement 저장과 추천 HTTP는 P2/P5 전환 과제로 분리 가능하고, 삭제된 rag 기반27건 등은 외부 검색 완료 증거가 아니다. 이러한 후속 과제와 P0 자체의 R1/R2를 혼동하지 않는다.

운영 DB 미적용(`service_db_applied:false`) 자체는 P0 개발 완료의 차단 조건이 아니다. 지시서는 전용 DB 검증을 허용하며 서비스 적용은 별도다. 인증 방식 변경도 사용자 지정 develop 정렬 범위에 포함되므로, 변경 사실만으로 승인을 막지 않는다. 핵심은 미충족 D0 게이트다.

## 다음 단계 진행 범위

- P1: 조건/도메인 버전 adapter 점검은 착수 가능. P0 수정과 통합 검증 후 완료 판단.
- P2: plan_node 기반 필요량과 조건 기반 보유량 저장 전환은 착수 가능. 보고서가 확인한 실패12건의 관련 경로를 수정한다. P0 저장소 API와 무결성 계약을 고정한 후 통합 완료 판단.
- P6: P1 소유권 산출물을 사용해 계정 설정/iat 무효화 검토 가능. 보고서의 인증28건 결과를 재사용하고 변경 경계만 확인한다.
- P3: 외부 provider 경계·미설정 unknown 처리 설계/구현 가능. P0 JSON 무결성 수정 전 DB 통합 완료 승인 불가.
- P4: 순수 계산/DTO 전환 준비 가능. P2/P3 통합 산출물에 대한 완료 게이트 유지.
- P5/P7: 현 P0를 완료로 간주해 통합 완료를 선언할 수 없다. P1~P4 등 원래 선행 조건도 필요.
- P8/P9: 기존 선행 조건 유지. 운영 준비 완료는 보류.

우선순위: R1/R2 공통 저장소 보완 → R3/R4 기존 HTTP 기능 보존 → 누락된 D0 증거 기록. 기존 전체 테스트 재실행 대신 새 결함 회귀와 영향받은 경로만 검증한다. 각 실패가 거부/rollback 및 사용자 결과 일치로 확인되면 P0를 재판정한다.
