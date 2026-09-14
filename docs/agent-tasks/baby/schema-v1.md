# Baby target schema — develop alignment v3

파일명은 기존 링크 호환을 위해 유지한다. **목표 기준은 develop `da79839`이며 아래 매핑은 구현할 계약이다. 현재 rag/서비스 DB가 이미 이 형태라는 선언이 아니다.** 이전35테이블·pgvector 유지·item 통합 설계는 폐기한다. 상세 JSON·동시성·SQL 전환은 [전환 계약](DEVELOP_DB_TRANSITION.md)을 따른다.

| 기능 | develop 목표 저장 위치 | 유아 코드 변경 |
|---|---|---|
| 도메인 규칙 | config.domain + domain_version | revision/run의 domain_version_id 사용; 정의/해시는 버전에서 읽음 |
| 세션/조건 | identity.conversation/message, planning.plan/plan_revision/plan_condition | 조건·게스트 소유권 유지; 조건 변경 lock_version |
| 슬롯/필요량 | planning.plan_node + requirement | template_key→DTO.slot_key; node_id 필수; quantity/unit_code/required와 match_spec.baby_requirement v3 |
| 보유량 | plan_condition 원본 + requirement.match_spec v3 | planning.item/owned_item/fulfilled_by_item_id 없음; fulfilled_qty와 조건 출처로 계산 |
| 추천/검증 | engine.recommendation_run/candidate/validation_result | domain_version_id, candidate.selected/qty/timing, 근거/issue JSON 배열 |
| 확정 구매 | planning.purchase_line | pack_count/line_amount/snapshot; 보유품 제외; 관측값 범위 검사 |
| 확정 보고의 조건/보유/합계 | completed run.input_snapshot.baby_confirmation | P7에서 한 번 고정; 이전 입력 키 보존; 과거 리포트는 snapshot만 읽음 |
| 상품 분류/단위 | catalog.product.category_id; 각 unit_code 컬럼 | membership/shared.unit 제거; 코드 단위 사전으로 검증 |
| 설명서 | assets.file_object/product_material/material_revision/material_applicability | 통합 product_material 컬럼 가정 제거; 게시 revision·권한·상품 범위 검사 |
| 출처/근거 | evidence.source + evidence.evidence | source_id 유지; 외부 검색 hit adapter 필요; 조회 때 유효성 재검사 |
| 후기 | community.review/review_revision 및 기존 pc_build 계열 | review_revision에 본문/평점/검수; 통합 review_component 가정 제거 |
| 요약/집계 | evidence.review_subject/summary/aggregate/member | domain_version별 분리; author_ref/review_posted_at 유지 |
| 계정 설정 | identity.app_user.ui_settings/notification_settings | user_preference 제거; develop iat 인증 방식으로 연결 |
| 기존 가격 알림 | notification.price_watch | 기존 develop 동작/참조 보존; 유아 발송 기능 신규 구현을 의미하지 않음 |
| 행동 기록 | engine.feedback_event | run/revision/candidate 범위 검사 유지 |
| RAG 청크/벡터/적재·검색 이력 | 외부 검색 provider | PostgreSQL rag 없음; 실제 backend 통합은 P3-D3-02 게이트 |
| 연구/정제 데이터 | 파일 | dataset 스키마 복원 금지 |
| 수정 시각 트리거 | shared.set_updated_at() | shared 스키마는 유지, unit 테이블만 제거 |

## P0 schema assertions

최종 DB에서 domain_version, plan_node, purchase_line, material_revision, material_applicability, evidence.source, review_revision, price_watch가 존재해야 한다. rag/dataset 스키마와 planning.item/owned_item/fulfillment_allocation, identity.user_preference, shared.unit, catalog.product_category_membership, engine.candidate_evidence/validation_target/validation_evidence, notification.notification_event/price_watch_evaluation은 없어야 한다. 컬럼·FK·CHECK·트리거·JSON 기본값도 검사한다. develop의 설명상38테이블은 참고값이며 실제 수와 migration ledger를 보고서에 기록한다.

JSON은 FK를 자동 제공하지 않는다. run/requirement/revision 관계, 상품·관측값·출처 범위, 보유 조건의 소유권, 선택 수량·단위, 근거 철회를 P0 공통 저장소 및 업무 트랜잭션에서 검증한다. 필요 제약은 유지 테이블에만 후속 추가한다. 구0013/0014의 검증 의도를 버리지 않되 삭제된 테이블/컬럼 제약 자체를 복원하지 않는다.

## 실측 결과 (이 파일이 아니라 reports/P0.md "2026-09-13 v3" 절이 근거)

이 파일의 위 단정문은 전부 실제 디스포저블 PostgreSQL에서 재확인됐다 — 정확한 명령·출력·남은
과제는 [`reports/P0.md`](reports/P0.md)의 "2026-09-13 v3 — develop `da79839` DB 정렬" 절을
근거로 본다. 요약: 테이블 38개, 위 단정 전부 통과, 전체 테스트 213 passed/12 explained-failed
(P2 유아 저장 경로, 이 문서 범위 밖)/30 skipped(P3 외부 검색 27 + 선택적 의존성 2 + 1), 실 HTTP로
PC 세션→추천→편집→확정→리포트 재현 완료. 이 문서 자체를 "완료 증거"로 인용하지 말 것 — 물리
계약 정의일 뿐이다.
