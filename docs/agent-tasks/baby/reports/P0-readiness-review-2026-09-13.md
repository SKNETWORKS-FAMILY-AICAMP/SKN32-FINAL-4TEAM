# P0 결과 검토 — P1/P2 착수 판단

> 후속 사용자 결정: 구 데이터 이관 없이 새 DB를 구축한다. 현재 실행·승인 기준은 [P0 지시서](../P0_schema_contracts.md)의 교체된 SR01–SR09다. 아래 과거 이관/매핑 조건은 대체됐으며 실제 코드 전환·스냅샷·무결성 검증은 여전히 필요하다. 이 문서의 과거 실행 기록은 완료 증거로 새로 해석하지 않는다.


검토 기준: `30af559` 기반 현재 작업 트리, P0 보고서의 **v2 continuation result**, 0010/0011 및 실제 저장소 코드. 과거 sync 감사보다 이후의 0011 보완 결과를 우선 검토했다. 구현 수정 없이 코드와 보고서를 검토하고 아래 테스트를 직접 재실행했다.

```yaml
review_status: changes_required
p0_status: partial
p1_integration_ready: false
p2_integration_ready: false
independent_preparation_allowed: true
verified_command: .venv/bin/python -m pytest -q tests/test_schema_reduction.py tests/test_recommendation_schemas.py
observed_result: 8 passed
```

## 판단

**현재 지시서 기준으로 P1과 P2 전체 구현을 다음 단계로 넘기면 안 된다.** CONTRACTS의 선행 작업 완료 조건이 충족되지 않았다. 다만 DB와 분리된 입력 검증·규칙·합성 데이터 작업은 먼저 준비할 수 있다. 이를 P1/P2 통합 완료나 P0 완료로 표시하지 않는다.

비개발자 관점에서는 새 저장 칸은 생겼지만, 기존 저장 칸을 계속 사용하는 경로와 새 저장 칸에 빠진 값이 남아 있는 상태다. 지금 DB 연동까지 확장하면 이후 같은 부분을 다시 수정해야 한다.

## 확인한 개선

- `db/seed.py`가 신규 도메인의 current version/definition/hash를 채운다. 초기 설치 후 비어 있던 필드를 보완했다.
- `PlanRepo.ensure_requirement`가 node의 revision 소속을 검사하고 slot_key/position을 기록한다.
- `EngineRepo.get_candidates`는 plan_node 조인 대신 requirement의 slot_key/position을 읽는다.
- 0011은 후보 근거/검증 결과 JSON과 slot_key에 준비 단계 제약을 추가한다.
- 이번 계약 테스트 8개는 통과했다. P0 보고서에는 별도 실제 PostgreSQL에서 전체 69개 및 합성 RAG 21/21 통과가 기록돼 있다. **이번 검토에서 그 전체 DB 실행을 재현한 것은 아니다.** 해당 성공 기록도 미구현 이관 승인 조건까지 통과했다는 뜻은 아니다.

## 착수를 막는 근거

| 항목 | 실제 코드/검증 근거 | P1/P2 영향 및 필요한 조치 |
|---|---|---|
| 새 revision 규칙 스냅샷 누락 | `src/repo/plan_repo.py:15` new_revision은 domain_id만 추가하고 domain_snapshot을 쓰지 않는다. 0010은 기존 행만 일회성 backfill하며 신규 행 기본값은 `{}`다. | P1의 새 목록이 어떤 규칙으로 생성됐는지 보존되지 않는다. P2의 domain_snapshot 입력도 실제 저장 경로에서 보장되지 않는다. 신규 생성 시 버전/정의/hash 스냅샷을 저장하고, 규칙 변경 뒤 기존 revision이 보존되는지 검증한다. |
| 이행 중인 DB 계약 | new_revision/session_service는 domain_version, ensure_requirement는 plan_node에 의존한다. ProductRepo.add_observation과 seed_catalog는 source_id/evidence.source를 사용한다. 0010/0011은 구 구조를 유지한다. | P1 도메인 연결과 P2 카탈로그·가격·보유품 저장을 목표 구조로 완성할 기반이 미완료다. P0에서 라이브 SQL 전환, 단위/출처/참조 제약을 확정하고 schema-v1을 실제 상태에 맞춘다. 업무 규칙 자체는 P1/P2 범위다. |
| 발표된 규칙 선택 불일치 | `db/seed.py:73`은 무조건 가장 큰 version_no를 택한다. 0011:4는 published_at 존재/시각을 우선한다. | 발표 v1과 미발표 v2가 함께 있으면 seed 재실행이 current를 미발표 v2로 바꿀 수 있다. 두 경로에 같은 발표 우선 정책을 적용하고 혼합 버전 fixture로 검사한다. |
| JSON 제약이 불완전 | 0011:15 CHECK는 누락 키에 SQL NULL을 반환할 수 있어 `{}` 등 불완전 객체를 거부하지 못한다. NOT VALID이므로 과거 행도 검증하지 않는다. slot_key NULL도 허용한다. EngineRepo.link_candidate_evidence는 ID/claim만 기록하고 JSON 모델 필수 material/version/hash/locator를 만들지 않는다. | P0의 공통 계약을 완료로 간주할 수 없다. 필수 키/타입·참조 범위·중복 검사를 실제 쓰기 경로에서 적용하고 기존 행까지 검증한다. 모든 이 문제를 P1/P2 업무 구현에 떠넘기지 않는다. |
| 승인 검증 부족 | tests/test_schema_reduction.py:49는 SQL/소스 문자열 존재 검사다. P0 보고서도 SR02/SR03/SR05 미완료 및 이번 PC HTTP 미실행을 명시한다. | 옛 데이터 이관, 모호한 매핑 적용, 새 데이터 쓰기와 실제 추천 회귀가 증명되지 않았다. 테스트 개수와 무관하게 아래 승인 증거가 필요하다. |

## 지금 가능한 범위

| 작업 | 선행 완료 전 준비 가능 | 아직 정식 진행 불가 |
|---|---|---|
| P1 | 한국어 입력 파서, born/prenatal 및 정확 월령/구간 구분, none/필드 타입 검증의 순수 함수와 단위 테스트 | 최종 축소 DB 기반 세션·revision·규칙 스냅샷 통합 및 완료 선언 |
| P2 | 스펙 사전 복구, 합성 카탈로그 JSON/검증기, 버전 고정 필요 품목 규칙, 단위 계산·보유 수량 분할의 순수 함수와 테스트 | 최종 카테고리/단위/출처/보유품 참조를 사용하는 DB seed·후보 조회 통합 및 완료 선언 |

준비 작업은 CONTRACTS의 공통 타입을 사용하고 가짜 DB 성공 응답으로 통합을 대신하지 않는다. P2 순수 로직은 P1 HTTP 완료를 기다릴 필요가 없지만, 정규화 조건 입력의 타입은 함께 고정해야 한다.

## 재검토 시 필요한 증거

1. SR02/SR03: 별도 DB에 과거 데이터(복수 분류, 다중 충족, 과거 설명서/근거 등)를 적재해 이관한다. 모호한 항목은 보고 후 중단하며, 명시 매핑을 실제 소비하여 재실행이 완료된다. ID/수량/연결 보존과 재실행 멱등성을 확인한다.
2. SR05: 삭제 대상에 대한 라이브 SQL을 전환하고 제약/삭제를 완료한다. P0 목표와 실제 물리 스키마를 일치시킨다. 기존 적용 0010/0011을 덮어쓰지 말고 다음 전진 마이그레이션을 사용한다.
3. SR07/SR08: 빈 DB setup_all → 새 게스트/카테고리/조건 → PC 추천 POST202 → GET done(기존 fixture 8개)를 실행한다. 신규 revision의 스냅샷, 새 requirement의 slot_key, 상품·가격·근거 참조를 실제 행으로 검사한다. 초기 requirement 0건에서 NULL 개수 0인 것만으로 새 쓰기 성공을 증명하지 않는다.
4. SR09: 공통 HTTP 및 JSON 계약을 실제 직렬화/저장 경로에서 검증한다. malformed JSON, 다른 revision/run 참조, 없는 ID, 중복 근거가 기대대로 거부/정리되는지 확인한다.
5. 보고서와 schema-v1/manifest에 결과를 반영한다. P0 완료 후 P1/P2는 서로의 최종 구현을 기다리지 않고 공통 타입·공유 파일 변경을 조율하며 진행 가능하다.

결론: P0는 유용한 보완이 반영된 partial이다. 전체 재작성은 불필요하나, 현재 계약을 유지하는 한 P1/P2의 DB 통합 착수는 P0 잔여 승인 조건 완료 후로 둔다.
