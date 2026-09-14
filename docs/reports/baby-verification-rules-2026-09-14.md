# 유아용품 전 품목 검증 규칙·증빙 — 실행 보고 (2026-09-14)

실행 지시서: [P3_full_catalog_verification_execution.md](../agent-tasks/baby/P3_full_catalog_verification_execution.md)
상위 설계: [유아용품 전 품목 검증 규칙 설계](../baby-verification-rule-design-2026-09-14.md)

## 요약

기본 유아 카탈로그 15개 필수 슬롯 전체에 규칙 레지스트리(`config/baby_verification_rules.yaml`)와
증빙 manifest(`data/baby/evidence/synthetic-demo-v1.yaml`)를 새로 만들고, `verify_baby_candidate()`를
"슬롯별 하드코딩 예외"(stroller만 검증됨) 구조에서 레지스트리·DB 증빙 기반 판정기로 다시 짰다.
합성 전용 DB에서 15개 슬롯 전부가 `pass` 후보 1건 + `unknown`/`fail` 후보 1건을 실제 적재 경로로
만든다. `bath`·`diaper` 조건은 실 HTTP(TestClient)로 재현해 최소 한 품목이 선택되고
`verification.synthetic_verification_only=true`가 표시됨을 확인했다.

이 작업 중 두 개의 기존 버그를 발견해 함께 고쳤다(둘 다 이 세션 이전의 미커밋 변경분에 있었음):

1. `verify_and_persist_baby_candidate`(운영 경로)가 `add_validation(...)`에 `issues=` 를 넘기지
   않아 `target`(candidate_id/requirement_id 연결)이 저장 시점에 소실되고 있었다 —
   `_stored_baby_missing_requirements`·`patch_item`의 검증 재확인이 항상 빈 결과를 봤다.
2. `issues[].evidence_ids` 키가 CONTRACTS.md·P3 문서가 명시한 `evidence_refs`와 이름이 달라
   실제로 한 번도 채워지지 않고 있었다(`tests/test_baby_recommendation_http.py`의 관련 assert가
   지금까지 `if evidence_rows:` 관대화 분기로 한 번도 실행되지 않았음).

## production_readiness: blocked

이 세션에서 실제 공식(국가기술표준원 등)·제조사 안전 문서를 새로 수집하지 않았다 — 문서
자체가 필요한 리서치이며, 존재하지 않는 원문을 `source.authority: official|manufacturer`로
꾸며 넣는 것은 P3 문서의 금지 사항이다. 따라서:

- `config/baby_verification_rules.yaml`의 모든 규칙은 `scopes: [synthetic_demo]`만 갖는다.
  `production` scope 규칙은 하나도 없다 — 로더가 이를 테스트로 보장한다
  (`test_canonical_registry_has_no_production_scope_rules_yet`).
- `scripts/import_baby_evidence.py --scope production`은 동작하지만(추후 실제 원문이
  준비되면 그대로 쓸 수 있음), `BABY_ALLOW_PRODUCTION_IMPORT=1`을 명시하지 않으면 거부한다.
- 실 카탈로그(corpus=real) 후보는 현재 파이프라인에 연결된 진입점이 없다
  (`get_baby_candidates(..., corpus="synthetic")`가 유일한 실행 경로) — 있었더라도
  `find_verification_rule(rules, slot, "production")`이 항상 `None`을 돌려주므로
  `scope_mismatch`/`no_reviewed_rule_for_category`로 unknown이 된다.

## 구현 내용

### 1. 규칙 레지스트리 (`config/baby_verification_rules.yaml`, `src/rag/verification.py`)

- `load_baby_verification_rules()`가 스키마·출처·범위·날짜를 검증한다: production 규칙은
  `official|manufacturer` + `https://`, synthetic_demo 규칙은 `synthetic_fixture` +
  `synthetic://`만 허용; `retrieved_on`은 미래일 수 없음; `rule_id` 전역 유일; 슬롯·범위
  조합 중복 금지; 15개 필수 슬롯 전부 있어야 함(`clothing`은 대상 목록에서 제외, 설계
  문서와 동일).
- `MANUAL_RULE_INVENTORY`/`REVIEWED_NOT_APPLICABLE`을 레지스트리의 "호환 뷰"로 바꿨다 —
  이제 존재하지 않는 rule_id를 가리킬 수 없다. `REVIEWED_NOT_APPLICABLE`은 여전히 빈
  dict다 — 검토된 비적용 근거가 이 세션에 하나도 만들어지지 않았기 때문.
- `optional_condition_claims`(월령·체중·독립 착석)는 `stroller`만 채웠다. 나머지 14개
  슬롯에 같은 형태의 규칙을 새로 만들려면 실제 규제·제조사 수치 출처가 필요한데, 이
  세션엔 없다 — 만들어 넣는 대신 금지 사항("제품군 이름만으로 적용 제도를 단정하지
  않는다")을 지켰다.

### 2. 증빙 manifest·적재기 (`src/rag/evidence_manifest.py`, `scripts/import_baby_evidence.py`, `scripts/seed_baby_synthetic_evidence.py`)

- `load_and_validate_manifest()`: 매 claim의 파일을 실제로 읽어 SHA-256을 재계산하고
  manifest에 적힌 값과 대조한다(불일치·파일 없음·미래 날짜·범위별 출처 규칙 위반은
  적재 전에 실패). DB를 건드리지 않는 순수 함수.
- `import_manifest()`: `catalog.product_fact` + `evidence.evidence` + (manufacturer_document
  claim은) `assets.product_material/material_revision/material_applicability`를 한
  트랜잭션으로 연결한다. 새 테이블은 만들지 않았다 — `catalog.product_fact`는 이미
  있었지만 `add_fact`/`verified_facts`가 `NotImplementedError`로 막혀 있던 것을 실제
  구현으로 채웠다. `stroller`(조건 검사가 실제로 구현된 유일한 슬롯)의
  manufacturer_document는 기존 `src.rag.ingestion.ingest_manual`(검색 provider까지
  색인)을 그대로 재사용하고, 나머지 14개 슬롯은 provider 색인 없이 문서 존재·게시
  상태만 등록한다(그 슬롯의 조건 layer를 아무도 검색하지 않으므로).
  같은 파일 해시·source_url·버전·claim 조합은 재사용(`claims_reused`), 다르면 이전
  `catalog.product_fact` 행을 `superseded`로 내리고 새 행을 만든다(과거 값을 덮어쓰지 않음).
- `seed_baby_synthetic_evidence.py`: 기 시드된 `data/baby/catalog_demo_v1.json`과
  기존에 생성돼 있던 `generated/synthetic_manuals/catalog_demo_v1_r1/*`(모든 188개 상품에
  대해 이미 존재하던, `실제 안전 평가: 미평가`가 명시된 합성 설명서)를 입력으로 manifest+
  claim 파일을 생성하고 바로 적재한다. 슬롯마다 pass 후보 1건(4 claim 전부 verified) +
  blocked 후보 1건을 만든다 — `bottle`/`car_seat`는 기존에 손으로 만들어져 있던 회수·미인증
  픽스처(`SYN-BOTTLE-RECALL-001`, `SYN-CARSEAT-CERT-001`)를 재사용하고, 나머지 13개
  슬롯은 두 번째 카탈로그 상품에 `product_identity`만 적재해 `missing_rule_evidence`를
  만든다. 멱등 — 재실행 시 `claims_imported=0, claims_reused=76`.

### 3. 판정기 (`src/engine/stage3c_verify.py`)

`verify_baby_candidate()`를 7단계로 다시 짰다(P3 문서 순서 그대로): ① scope로 규칙
조회 ② 상품 식별·증빙 조회(`ProductRepo.resolve_ids`/`verified_facts`, scope로 필터)
③ manufacturer_document의 게시 상태 재확인 ④ `recall_status`가 `active*`면 무조건 fail
⑤ `required_claims` 전부 verified 아니면 unknown ⑥ 조건 layer(stroller만, 기존
`verify_seat` 재사용) ⑦ 전부 통과해야 pass. 기존 `candidate["facts"]`(카탈로그 시드에
직접 박아 넣은 JSON) 경로는 완전히 제거했다 — 모든 판정이 실제 DB 증빙 조회를 거친다.

## 규칙 커버리지

```yaml
scope: synthetic_demo
rule_coverage:
  required_slots: [bottle, formula, high_chair, baby_food, crib, sleepwear, stroller,
                    car_seat, bath, skincare, diaper, wipes, mat, gate, thermometer]
  configured_slots: [bottle, formula, high_chair, baby_food, crib, sleepwear, stroller,
                      car_seat, bath, skincare, diaper, wipes, mat, gate, thermometer]
  missing_slots: []
evidence_coverage:
  pass_candidate_count_by_slot:
    bottle: 1
    formula: 1
    high_chair: 1
    baby_food: 1
    crib: 1
    sleepwear: 1
    stroller: 1
    car_seat: 1
    bath: 1
    skincare: 1
    diaper: 1
    wipes: 1
    mat: 1
    gate: 1
    thermometer: 1
  blocked_candidate_count_by_slot:
    bottle: 1
    formula: 1
    high_chair: 1
    baby_food: 1
    crib: 1
    sleepwear: 1
    stroller: 1
    car_seat: 1
    bath: 1
    skincare: 1
    diaper: 1
    wipes: 1
    mat: 1
    gate: 1
    thermometer: 1
  reasons_by_slot:
    bottle: active_recall            # SYN-BOTTLE-RECALL-001, verified recall_status
    car_seat: missing_rule_evidence  # SYN-CARSEAT-CERT-001, identity만 적재
    formula: missing_rule_evidence
    high_chair: missing_rule_evidence
    baby_food: missing_rule_evidence
    crib: missing_rule_evidence
    sleepwear: missing_rule_evidence
    stroller: missing_rule_evidence
    bath: missing_rule_evidence
    skincare: missing_rule_evidence
    diaper: missing_rule_evidence
    wipes: missing_rule_evidence
    mat: missing_rule_evidence
    gate: missing_rule_evidence
    thermometer: missing_rule_evidence
tests:
  command: |
    export DATABASE_URL='postgresql://truefit:truefit@127.0.0.1:5432/truefit_baby_rules_test?sslmode=disable'
    export RAG_TEST_DATABASE_URL="$DATABASE_URL"
    export BABY_SEARCH_PROVIDER=local-file
    export BABY_SEARCH_STORAGE_ROOT=.baby-search-index
    uv run python scripts/setup_baby_demo.py
    uv run python -m pytest -q \
      tests/test_baby_verification_rules.py \
      tests/test_baby_evidence_import.py \
      tests/test_baby_verification.py \
      tests/test_baby_optimizer.py \
      tests/test_baby_recommendation_http.py \
      tests/test_result_interaction.py \
      tests/test_list_service.py
  result: "114 passed, 13 failed — see '기존 실패, 이 작업과 무관' below. 이 작업이 새로 만든 세 파일(test_baby_verification_rules/test_baby_evidence_import/test_baby_verification)은 65/65 전부 통과."
browser:
  bath_case: pass   # 실 브라우저는 이 환경에 없음 — 실 FastAPI TestClient(모킹 없음)로 재현: 30개월·목욕·위생·특이사항 없음·보유 없음·30만원 → feasible=true, bath 1건 선택, verification.synthetic_verification_only=true
  diaper_case: pass # 동일 방식: 기저귀·배변 need, 30만원 → feasible=true, diaper 1건 선택
production_readiness: blocked
remaining:
  - "실제 공식/제조사 안전 문서 수집 — 국가기술표준원 어린이제품 안전 특별법 시행규칙
    별표(적용 범위)와 실제 판매 상품의 KC 인증·리콜 조회 결과가 필요하다. 이건 AI
    에이전트가 이 세션 안에서 만들어낼 수 없는 실제 리서치·문서 검토 작업이다."
  - "condition layer(월령·체중 등)를 stroller 외 나머지 슬롯에도 만들려면 각 품목의
    실제 안전기준 수치 출처가 있어야 한다 — 지어내지 않았다."
  - "실 카탈로그(corpus=real) 후보 수집 경로 자체가 아직 파이프라인에 연결돼 있지
    않다(현재 get_baby_candidates는 corpus=synthetic 고정 호출) — 이건 P3 범위 밖의
    카탈로그/제휴 커머스 연동 작업이다."
  - "이 보고서와 무관하게 이미 실패 중이던 tests/test_baby_recommendation_http.py 6건,
    tests/test_password_auth_http.py 7건, tests/test_feedback_events.py/test_list_service.py/
    test_result_interaction.py 일부, tests/test_schema_reduction.py 1건,
    tests/test_migration_0009_compatibility.py 4건 — 전부 이 세션 시작 전 커밋되지 않은
    변경분(engine_repo.py/recommendation_service.py) 또는 그 이전부터 존재하던 문제로,
    git stash로 대조 확인했다(정확히 같은 실패가 수정 전 코드에서도 재현됨)."
```

## 기존 실패, 이 작업과 무관

`git stash`로 이 세션의 모든 변경을 걷어낸 뒤 같은 테스트를 같은 디스포저블 DB에 돌려
정확히 같은 실패 목록을 확인했다 — 아래는 이 세션이 만들거나 악화시킨 것이 아니다.

- `tests/test_baby_recommendation_http.py`: `test_rh01_owned_item_is_never_charged`,
  `test_rh03_forged_candidate_on_swap_is_rejected`, `test_rh05_patch_qty_and_stale_lock_version`,
  `test_rh05_alternatives_and_swap_recompute_totals`,
  `test_rh06_recommendation_shown_event_emitted_once_and_get_generates_none`,
  `test_p7_confirm_rejects_when_mandatory_requirement_is_uncovered`(마지막 것은 이 세션에서
  차단 시나리오 구성 방식만 고쳤다 — car_seat가 이제 실제로 통과 가능해졌기 때문에 예산
  대신 후보 삭제로 "필수 품목 미충족"을 재현하도록 바꿨지만, 남은 실패 원인은 confirm()의
  `stale_recommendation`(409) vs 기대값(422) 불일치로 이 세션 이전부터 있던 별개 버그다).
- `tests/test_password_auth_http.py` 7건 — 인증/락아웃/동시성 테스트, 유아 검증과 무관.
- `tests/test_feedback_events.py`, `tests/test_list_service.py`, `tests/test_result_interaction.py`
  일부 — 전부 컴퓨터(PC) 카테고리 경로에서 발생하며, `git stash` 상태에서도 동일하게 실패.
- `tests/test_schema_reduction.py::test_migration_chain_matches_develop_exactly` — `0014_candidate_checks.sql`이
  develop 목표 체인에 없는 로컬 전용 마이그레이션이라 발생, 이 세션 이전부터 존재.
- `tests/test_migration_0009_compatibility.py` 4건 — `db/compatibility/0009_existing_identity_fields.sql`
  파일 자체가 저장소에 없어서(`FileNotFoundError`) 발생, 이 세션과 무관.

## 변경 파일

```text
config/baby_verification_rules.yaml            (신규)
data/baby/evidence/synthetic-demo-v1.yaml       (신규, 생성됨)
data/baby/evidence/files/*.json                 (신규, 생성됨, 62개)
src/rag/verification.py                         (레지스트리 로더·검증기 추가, verify_seat는 그대로)
src/rag/evidence_manifest.py                    (신규)
src/engine/stage3c_verify.py                    (verify_baby_candidate 전면 재작성)
src/repo/product_repo.py                        (add_fact/verified_facts/resolve_ids 구현)
src/repo/engine_repo.py                         (이 세션 이전 미커밋 변경분 — link_validation_target v3 어댑터, 그대로 유지)
src/services/recommendation_service.py          (verify_and_persist_baby_candidate의 issues= 누락 버그 수정,
                                                   _BABY_BLOCKERS 신규 reason 9종 추가,
                                                   synthetic_verification_only/synthetic_notice 추가)
src/schemas.py                                  (VerificationOut에 synthetic_verification_only/synthetic_notice 추가)
scripts/import_baby_evidence.py                 (신규)
scripts/seed_baby_synthetic_evidence.py         (신규)
scripts/setup_baby_demo.py                      (신규)
tests/test_baby_verification_rules.py           (신규, 16 tests)
tests/test_baby_evidence_import.py              (신규, 12 tests)
tests/test_baby_verification.py                 (신규, 37 tests)
tests/test_baby_recommendation_http.py          (evidence_refs 키 수정, P7 테스트 시나리오 구성 방식 수정)
tests/test_p1234_review_fixes.py                (레지스트리 전면 커버로 무효해진 전제를 실제 DB 기반 테스트로 교체)
```

## 금지 사항 준수 확인

- `unknown`을 UI/서비스 계층에서 `pass`로 치환하지 않았다 — `CandidateCheck._selection_requires_pass`가
  구성 시점에 이를 막는다(기존 가드, 그대로 유지).
- 합성 source/certificate/claim을 production 후보에 연결하지 않았다 — production
  scope 규칙 자체가 없고, 로더가 scope별 authority를 강제한다.
- 삭제된 `rag` 스키마·`engine.validation_target`을 복원하지 않았다 — `issues` JSON
  배열만 썼다(기존 v3 어댑터 그대로).
- 제품명 유사도로 제조사·모델을 추정 매핑하지 않았다 — `stable_id(product_key)`로
  카탈로그 행과 1:1 대응, 없는 상품은 `missing_product_identity`.
- 테스트 fixture를 `CandidateCheck(pass)`로 직접 주입해 성공 근거로 쓰지 않았다 — 모든
  pass/blocked 픽스처는 `scripts/import_baby_evidence.py`의 실제 적재 경로를 통과했다.
