# Develop DB alignment — contract v3

- decision_date: 2026-09-13
- target_commit: `da798393850c03866374b05c01eed568fbc84f71` (develop)
- inspected_source: `421b7eab5825c5932990861db044cfdd8bd9d94e` (rag) + 현재 미커밋 변경
- status: documentation_only; implementation_and_target_db_validation_pending
- authority: 사용자 요청 > 이 문서와 각 Pn의 ACTIVE DB CONTRACT > 기존 문서의 충돌하지 않는 업무/API 규칙. `개발 역할 분담`은 제외한다.

## Decision and scope

유아 서비스를 **develop의 부분 축소 DB에 맞춘다.** 이전의 완전 축소·PostgreSQL RAG 유지 지시를 대체한다. 원래 기획의 조건 수집·필수 수량·보유량 차감·안전 검증·예산·구매 시점·확정 스냅샷은 유지한다. 전부 처음부터 재작성하지 않는다. P0 저장소 호환을 먼저 완료하고 P1/P2/P6의 독립 전환, P3/P4, P5/P7, P8 이벤트 통합, P9 순서로 진행한다. 외부 검색이 미정이어도 DB/조건/순수 계산 작업은 진행할 수 있지만 검색 포함 완료로 승인하지 않는다.

이번 변경은 **문서 작성**이다. SQL·실행 코드 삭제, DB 초기화, 운영 연결 전환을 수행하지 않았다. 과거의 서비스 DB 초기화 기록은 develop 설치 완료 기록이 아니다.

## Source evidence and current gaps

- develop `046eb84`: `0011_drop_rag_schema.sql`과 `0012_schema_reduction_safe_subset.sql`.
- develop `da79839`: `0013_result_item_interaction.sql`, 결과 편집·사양 첨부.
- 현재 rag의 `src/engine/stage2_requirement.py`는 planning.item/fulfilled_by_item_id를 저장한다. `src/repo/engine_repo.py`는 domain_id/requirement.slot_key와 통합 근거 구조를 사용한다. develop의 PlanRepo는 domain_version_id/plan_node/purchase_line을 사용한다.
- [병합 검증](reports/merge-validation-2026-09-13.md): 당시 혼합 설치에서 rag 삭제 뒤 ALTER rag 실패, 통합 테스트 수집 실패. 이미 있는 로그를 재사용했고 이번 문서 작업에서는 테스트를 반복하지 않았다. 현재 파일 상태와 당시 병합 상태가 같다는 뜻은 아니다.
- [SQL 검토](reports/merge-sql-necessity-review-2026-09-13.md)는 이전 설계 유지 시 SQL이 필요한 이유와 서비스 DB 적용 이력을 설명한다. 그 보고서의 “pgvector 유지 권고”는 이번 사용자 방향으로 대체된다. 보고서 자체는 과거 증거로 보존한다.

## SQL execution policy for P0

| 대상 | 후속 구현 처리 |
|---|---|
| develop 원본0000~0009, `0010_review_summary_relation_axis.sql` | develop 버전을 기준선으로 보존. 파일명 전체가 migration key다. 같은 숫자만 보고 삭제하지 않는다. 원본 초기 SQL에서 rag를 만들고0011에서 지우는 중간 단계는 허용하되 최종 rag는 없어야 한다. 초기 체인이 vector 확장을 요구한다면 설치 전제에 그대로 기록한다. |
| develop `0011_drop_rag_schema.sql`, `0012_schema_reduction_safe_subset.sql`, `0013_result_item_interaction.sql` | 모두 보존/통합한다. 현재 rag checkout에는 없으므로 파일을 가져와야 한다. 최종 형태를 schema-v1과 대조한다. |
| rag `0010_schema_reduction_v1.sql`, `0011_schema_reduction_completion.sql`, `0012_schema_reduction_destructive.sql`, `0013_schema_reduction_scope_constraints.sql`, `0014_item_reference_integrity.sql` | develop 신규 설치 실행 체인에서 제거하는 전환 대상. 이 파일을 삭제하는 것만으로 구현이 끝나지 않는다. 참조 코드·시드·테스트를 동시에 전환하고 무결성 검증을 유지 테이블/저장소에 이식한다. 기존 서비스 DB 이력을 수정해 적용된 SQL이 없었던 것처럼 만들지 않는다. |
| `db/compatibility/0009_existing_identity_fields.sql` | 새 DB 전용 정책에서 레거시 호환 경로를 종료할 경우 파일·migrate.py 분기·전용 테스트를 함께 정리한다. develop 기본 SQL→원본0009의 새 설치 성공을 먼저 증명한다. 이 파일만 삭제하면 runner가 실패한다. |
| rag `0015_auth_version.sql` | v3는 develop iat 기반 인증에 맞추므로 코드 claim/사용자 조회/fixture의 auth_version 의존 제거와 함께 실행 대상에서 제외한다. 비밀번호 변경·탈퇴 토큰 거절은 P6-D6으로 유지한다. |
| 이후 추가 제약 | 유지 테이블의 꼭 필요한 무결성 보강만 다음 미사용 전체 파일명으로 추가. 이미 적용된 SQL 수정·체크섬 위조 금지. 완전 축소 구조를 되살리는 우회 SQL 금지. |

새 develop 전용 DB를 만들어 먼저 검증한다. 기존 서비스가 이전 완전 축소 구조이면 역방향 ALTER를 추정 실행하지 않는다. 실제 대상/이력을 확인해 초기화 또는 새 DB 연결 전환을 별도 적용 절차로 수행한다. 이번 문서 갱신은 그 실행이 아니다.

## Canonical storage adapters — to implement, not existing guarantees

### Domain, requirements, ownership

- `plan_revision.domain_version_id`와 `recommendation_run.domain_version_id`는 같은 선택 버전이어야 한다. definition/content_hash는 config.domain_version에서 읽는다. `run.input_snapshot`에 조건과 사용한 정의/해시를 넣어 실행 중 규칙 변화와 분리한다. 통합 domain의 definition/domain_snapshot 컬럼을 가정하지 않는다.
- requirement.slot_key는 물리 컬럼이 아니다. `requirement.node_id -> plan_node.template_key`를 통해 DTO에 공급한다.
- requirement의 총량은 quantity/unit_code/required. `match_spec.baby_requirement`의 현재 저장 payload는 다음 v3로 쓴다. 나머지 match_spec 키는 보존한다.

```json
{"schema_version":3,"id":"requirement UUID","revision_id":"revision UUID","slot_key":"bottle","group_key":"feeding","required_qty":2,"unit_code":"each","mandatory":true,"timing":"now","constraints":{},"fulfilled_qty":1,"owned":[{"source_condition_id":"same revision active condition UUID","label":"젖병","qty":1,"unit_code":"each"}]}
```

- owned.qty는 검증된 부모 조건에서만 만들고 총 fulfilled_qty는 같은 단위·품목의 실제 충족분 합(0~required_qty)이다. supplied qty를 맹신하지 않는다. DTO `fulfilled_by_item_id`는 폐기하고 모든 producer/consumer/fixture를 함께 수정한다. 보유 표시 ID는 `owned:<requirement UUID>:<condition UUID>`로 파생하며 DB UUID/FK가 아니다. 여러 보유 물품은 각각 표시하되 하나의 필요량을 중복 충족하지 않는다.
- 조건 수정으로 run이 stale이면 기존 필요량 payload도 다시 생성한다. 다른 revision의 조건/노드/필요량 연결을 거부한다. 변경 없는 슬롯은 실제 requirement UUID를 재사용한다.

### Candidate edits and confirmation

- 추천 후보/사용자 선택: `engine.recommendation_candidate`의 result와 selected는 별개다. qty=구매 팩 수(1~99), timing=now|soon|later. 유아 HTTP 구매 item_id는 requirement UUID, candidate_id는 선택된 recommendation_candidate.id. PC item_id는 기존 계약을 유지한다. frontend에서 구분을 적용한다.
- 사용자 편집/후보 교체는 revision row lock+lock_version 비교 하에 한 슬롯의 선택 후보 하나만 남긴다. 보유 행은 이 API로 수정하지 않는다.
- 확정 구매 행은 `planning.purchase_line(revision_id,offer_id,selected_observation_id,pack_count,line_amount,currency,snapshot)`이다. snapshot은 version=3, requirement_id, candidate_id, variant_id, product_key/name, source URL, unit_price, qty, unit_qty, unit_code, timing, 관측 시각, 검증 상태·근거 참조를 담는다. 실제 산출한 값만 쓴다.
- 확정 전 offer/관측값/variant 관계, 필수 안전·수량·예산을 다시 검증한다. 총액은 now만 청구 대상으로 표시하고 soon/later는 별도 합계다. 보유품은 구매 행을 만들지 않는다.
- 보유·조건·부족량·합계 포함 확정 보고 payload는 `run.input_snapshot.baby_confirmation`에 version=3, confirmed_at, condition snapshot, owned rows, totals, missing_requirements를 함께 고정한다. 기존 실행 입력 키는 바꾸지 않는다. JSON 전체 입력을 덮어쓰거나 input_hash를 재계산하지 않는다. 이 추가 키를 입력 hash 대상에서 제외하도록 hash 생성/검증 코드를 함께 정리한다. 해당 completed run을 잠그고 한 번만 기록하며 이후 불변이다. 리포트는 이를 가진 확정 run을 사용한다. 완전한 초기 snapshot 불변을 요구하는 기존 지시는 이 단일 확정 키 추가로 대체한다.
- confirmed revision에 다시 요청하면 기존 purchase_line과 확정 snapshot을 반환한다. 후속 변경은 새 draft revision으로 분리한다. 리포트가 최신 candidate나 가격에 따라 달라져서는 안 된다.

### Evidence and external search

- candidate.evidence_refs는 **JSON 배열**이다. 이전 `{schema_version:1,refs:[]}` wrapper 저장은 폐기한다. 내부 wrapper DTO가 필요하면 저장 경계에서 `.refs`로 변환하고 배열을 읽어 복원한다. validation_result.issues도 배열이다. 개별 참조/issue의 검증 규칙은 유지한다.
- 참조 최소 필드: evidence_id, claim_key, material_id, material_version, file_sha256, locator. 외부 검색 메타데이터: provider, external_hit_id. retrieval_run_id는 선택 사항이며 PostgreSQL rag UUID/FK 존재를 요구하지 않는다. JSON target은 candidate_id/requirement_id; 폐기된 planning.item UUID가 아니다.
- `evidence.source`는 유지된다. `evidence.evidence.source_id`로 출처를 연결한다. material_revision의 게시 상태, applicability의 상품/옵션/verified와 file_object의 권한·해시를 서버에서 재검사한다.
- develop은 rag 테이블만 삭제하고 evidence.retrieval_hit_id 컬럼과 material kind CHECK는 남긴다. 외부 검색 hit의 앱 UUID+provider/external_hit_id를 기록하는 P3 adapter가 필요하다. 삭제된 FK가 남긴 ID만으로 근거 진위를 인정하지 않는다.
- 외부 backend 제품·실행 설정은 미확인이다. P3-D3-01(provider 경계/미설정 상태/DB 검증)과 D3-02(실제 외부 적재·검색·철회)를 분리한다. 미설정은 unknown, 필수 안전 자동 선택 불가. 실제 안전 데이터/설명서가 부족한 품목도 unknown이다. 자료 없는 품목을 “무해당”으로 승인하지 않는다.

## Verification and reporting

문서 버전3은 DB adapter 및 내부 저장 계약의 변경이며 전체 HTTP API를 v3 URL로 바꾸라는 뜻이 아니다. Pn별 Dn 수용 사례를 현재 DB에서 증명한다. 기존 보고서의 명령/결과/코드 경로를 대조하고 변하지 않은 테스트 실적을 재사용한다. DB 경로 변경으로 효력이 사라진 실적과 실제 새 검증을 분리한다. 테스트를 삭제하거나 건너뛰어 완료로 만들지 않는다.

각 `reports/Pn.md`에 기존 기록을 보존하고 다음 절을 추가한다:

```yaml
contract_version: 3
target_db_commit: da798393850c03866374b05c01eed568fbc84f71
status: complete | partial | blocked
implementation_commit_or_tree: actual
changed_files: []
reused_evidence: [{report: path, cases: [], rationale: unchanged_path}]
new_tests: [{command: actual, result: actual, cases: []}]
acceptance: {Dn: pass_or_fail_or_blocked}
reproduction: []
remaining: []
service_db_applied: false
```

문서 갱신만으로 기존 보고서를 새 계약 complete로 바꾸지 않는다.
