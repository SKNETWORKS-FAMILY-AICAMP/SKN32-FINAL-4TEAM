# 병합 SQL 필요성 검토 — 2026-09-13

결론: **가져온 SQL을 일괄 삭제하면 안 된다.** 현재 유아 구현과 이미 초기화한 서비스 DB는 rag/pgvector 유지·완전 축소 구조를 사용한다. develop의 RAG 삭제·부분 축소 구조와 동시에 유지할 수 없다. develop 우선 충돌 해결은 상반된 DB 설계 사이의 자동 호환을 보장하지 않는다.

이번은 코드/SQL 및 서비스 DB 적용 이력의 읽기 전용 검토다. SQL 적용·삭제, 서비스 DB 변경, 기존 테스트 재실행은 하지 않았다. 직전 병합 검증에서 확인한 빈 DB 설치 실패를 근거로 재사용했다.

## 가져온 파일별 판정

| 파일 | 실제 역할 | 필요성·처리 판단 |
|---|---|---|
| db/compatibility/0009_existing_identity_fields.sql | 과거 기본 SQL에 이미 존재하는 인증 컬럼/트리거를 검증하고 누락분만 생성 | **레거시0008 설치 지원 시 필요.** 새 DB에서는 원본0009로도 설치 가능하지만 현재 migrate.py가0009 적용 때 이 파일을 직접 읽으므로 단독 삭제 금지. 사용자 서비스 DB에서 실제 중복 컬럼 오류를 해결한 이력이 있다. 현재 서비스는0009 적용 완료라 재실행하지 않는다. 지원 경로를 폐기할 때 러너 분기·테스트도 함께 정리해야 한다. |
| 0010_schema_reduction_v1.sql | domain 통합 컬럼, requirement.slot_key, planning.item, 근거 JSON 등 준비/기존 행 변환 | **현재 유아 코드에 필요.** PlanRepo.new_revision, EngineRepo.start_run, baby 저장소가 이 구조를 쓴다. 일부 ALTER가 IF NOT EXISTS여도 뒤쪽은 구 테이블을 읽으므로 재실행 가능한 범용 복구 SQL은 아니다. |
| 0011_schema_reduction_completion.sql | 도메인 값 보완, JSON 기본 구조 CHECK, slot 인덱스 | **현재0010→0012→0013 체인의 일부로 필요.** 더 강한0013 제약이 있다는 이유로 이미 적용된 이 파일을 삭제하지 않는다. 향후 새 설치 기준선 통합 때만 재구성 검토 가능. |
| 0012_schema_reduction_destructive.sql | 구 테이블 제거, domain_id·item·통합 material/evidence 구조 전환, shared 트리거 이전, rag 유지 | **유아 완전 축소 구조에는 필요하지만 현재 develop 코드/SQL과 충돌.** domain_version·purchase_line·notification.price_watch를 사용하는 develop 경로도 이 구조에 맞춰 전환해야 한다. 안전한 단독 추가 마이그레이션으로 볼 수 없다. |
| 0013_schema_reduction_scope_constraints.sql | 근거 JSON 필수값·중복·존재/실행 범위, 후보 revision 관계, 규칙 스냅샷 제약 | **유아 검증 계약 유지에 필요.** 빠지면 과거 확인된 잘못된 참조·스냅샷 문제가 다시 열린다. rag와0012 결과를 전제한다. |
| 0014_item_reference_integrity.sql | item의 실제 목록/옵션/판매처/관측값 참조 및 같은 revision의 충족 관계 강제 | **planning.item 유지 시 필수.** 실제 재현된 고아 item/미존재 충족 참조를 막은 수정이다. develop-only에는 item 자체가 없지만 현재 병합된 유아 저장 경로는 사용한다. |
| 0015_auth_version.sql | 계정별 인증 세대 컬럼/음수 방지 CHECK | **P6 세대 기반 토큰 무효화를 유지할 때 필요. 현재는 코드 통합부터 필요.** jwt.verify는 auth_version을 요구하지만 jwt.issue는 해당 claim을 만들지 않고, deps와 user_repo/auth_service에도 세대 조회·증가 연결이 없다. SQL만 적용해도 인증은 고쳐지지 않는다. develop의 iat 방식만 유지하기로 한다면 불필요할 수 있으나 P6 계약·토큰 코드·테스트를 함께 바꿔야 한다. |

## develop SQL과의 구체적 충돌

1. `0011_drop_rag_schema.sql`은 rag를 삭제한다. 뒤의 가져온0012는 rag.ingestion_job 등을 ALTER하여 실패한다. 직전 빈 DB 검증에서 실제 재현했다. RAG/pgvector 유지 방침이면 이 삭제 경로를 신규 설치에서 실행하지 않도록 정리해야 한다. 이미 삭제가 적용된 다른 DB라면 파일 제거만으로 rag가 돌아오지 않는다.
2. `0012_schema_reduction_safe_subset.sql`은 가져온0010에서 추가한 app_user.ui_settings, product.category_id, candidate.evidence_refs 등을 다시 ADD한다. 가져온0012_destructive가 먼저 실행되므로 이미 없어진 user_preference·shared.unit·owned_item 등을 다시 조회/삭제하기도 한다. 단순 IF NOT EXISTS 처리로는 데이터 의미와 삭제 순서를 해결할 수 없다.
3. safe_subset의 evidence_refs 기본값은 배열 `[]`인 반면 유아 계약은 `{schema_version:1,refs:[]}` 객체다. 이름이 같다고 동일 변경이 아니다.
4. `0013_result_item_interaction.sql`의 candidate.selected/qty/timing은 develop의 EngineRepo.update_candidate_state가 사용하므로 **별도로 필요한 develop 기능**이다. 유아 item.qty/timing과 저장 위치가 다르다. 자동으로 중복이라고 삭제하지 말고 PC 후보 편집과 유아 item 편집의 저장 경계를 정해야 한다.
5. 기존 `0010_review_summary_relation_axis.sql`은 review_summary의 작성자 참조·게시시각을 추가한다. 가져온 축소0010과 파일 번호가 같아도 역할은 다르다. 실행기는 파일명 전체를 이력 키로 쓰므로 번호 중복 자체가 실패 원인은 아니다.

## 실제 서비스 DB 이력이 뜻하는 것

localhost:5432/truefit의 읽기 전용 이력 조회 결과:

- 원본0000–0009, review_summary0010 및 가져온 축소0010–0014 적용 완료.
- develop의0011_drop_rag_schema/0012_safe_subset/0013_result_item_interaction과 가져온0015_auth_version은 이력에 없다.

따라서 **현재 상태에서 서비스 DB에 setup_all을 재실행하지 않는 것이 맞다.** 실행기는 현재 파일 중 미적용 파일을 번호와 무관하게 찾아 적용하므로, 나중0014가 적용됐어도 이전 번호의 RAG 삭제가 새로 실행될 수 있다. 이미 적용된 축소 파일을 지우면 다음 새 DB 설치가 현재 서비스 구조를 재현하지 못한다.

## 권고

기존 사용자 결정과 유아 기능을 유지한다면 가져온 축소0010–0014 및 레거시 호환 파일을 보존하고, develop의 중복/상충 축소 경로와 구 테이블 소비 코드를 하나의 설계로 통합한다. 결과 편집0013은 필요한 컬럼만 호환되게 유지한다. 인증0015는 토큰 발급·검증·세대 증가 코드와 함께 통합한다.

반대로 develop의 부분 축소/별도 벡터DB 방향으로 완전히 전환하려면 가져온 SQL만 삭제하는 수준이 아니라 유아 저장소·RAG·검증·시드·테스트와 이미 축소된 서비스 DB의 이전 계획을 함께 재설계해야 한다. 이번 사용자의 “필요성 검토”를 그 아키텍처 전환 승인으로 해석하지 않는다.
