# P3 — 유아용품 전 품목 검증 규칙·증빙 실행 지시서

작성일: 2026-09-14  
상위 설계: [유아용품 전 품목 검증 규칙 설계](../../baby-verification-rule-design-2026-09-14.md)

## 목표

기본 유아 카탈로그의 15개 품목 슬롯에 대해 규칙·증빙·판정·결과 전달 경로를 구현한다.
합성 개발 카탈로그에서는 일반 추천 실행을 통해 선택 가능한 후보를 만들고, 실제 상품에서는
공식 또는 제조사 증빙을 갖춘 제품만 선택한다. 근거가 없거나 범위가 맞지 않으면 자동 선택과
확정을 계속 차단한다.

이 작업은 `unknown`을 일괄 `pass`로 바꾸거나, `REVIEWED_NOT_APPLICABLE`에 품목을
일괄 추가하는 작업이 아니다.

## 시작 전 필수 확인

1. 저장소의 `AGENTS.md`, `DEVELOP_DB_TRANSITION.md`, `schema-v1.md`, `CONTRACTS.md`를
   읽는다. 현재 DB 계약은 v3이며 삭제된 `rag` 스키마와
   `engine.validation_target`을 복원하지 않는다.
2. `config/baby_requirement_rules.yaml`의 필요 품목과
   `data/baby/catalog_demo_v1.json`의 카탈로그 슬롯을 비교한다.
3. 현재 `src/rag/verification.py`, `src/engine/stage3c_verify.py`,
   `src/repo/engine_repo.py`, `src/services/recommendation_service.py`의 실제 내용을
   확인한다. 문서의 줄 번호나 과거 보고서보다 현재 코드를 우선한다.
4. DB 검증은 새 전용 PostgreSQL DB에서만 실행한다. 기존 서비스 DB, 사용자 장바구니,
   기존 증빙 자료를 삭제·초기화하지 않는다. 실행 전 `DATABASE_URL`의 DB 이름과 호스트를
   출력해 대상이 전용 DB인지 확인한다.

## 범위와 완료 조건

### 대상 슬롯

다음 15개 슬롯은 규칙 레지스트리에 반드시 있어야 한다.

```text
bottle formula high_chair baby_food crib sleepwear stroller car_seat
bath skincare diaper wipes mat gate thermometer
```

`clothing`은 현재 카탈로그가 없는 `data_gap`이다. 카탈로그·공식 분류·제품 증빙 없이
규칙만 만들어 선택 대상으로 바꾸지 않는다.

### 완료 정의

- 모든 대상 슬롯의 규칙이 형식·출처·범위 검증을 통과한다.
- 합성 전용 DB에서 각 슬롯마다 일반 적재 경로를 거친 pass 후보가 하나 이상 있고,
  missing/unknown/fail 후보도 하나 이상 있다.
- `bath` 조건(30개월, 목욕·위생, 특이사항 없음, 보유 없음, 30만원)이 API와 브라우저에서
  최소 한 개의 선택 품목을 반환한다. 결과는 합성 검증 범위임을 표시한다.
- 실상품 후보는 공식 또는 제조사 증빙·제품 식별·적용 범위가 모두 맞을 때만 pass다.
- 제공자 오류, 출처 부재, 식별 불일치, 회수, 인증 불일치, 조건 불충족은 원인별 코드로
  unknown 또는 fail이며 선택·확정할 수 없다.
- 조회는 재검색·재추천을 하지 않고 저장된 `issues` JSON만 읽는다.

## 데이터 계약

### 규칙 레지스트리: `config/baby_verification_rules.yaml`

새 파일을 만들고 스키마 검증기를 함께 구현한다. 규칙에는 아래 필드가 필수다.

```yaml
schema_version: 1
rules:
  - rule_id: baby.bath.evidence.v1
    rule_version: v1
    slot_key: bath
    scopes: [synthetic_demo, production]
    applies_when: {market: KR}
    required_claims:
      - product_identity
      - safety_route
      - manufacturer_document
      - recall_status
    optional_condition_claims: []
    pass_when: all_required_claims_verified
    unknown_when:
      - missing_rule_evidence
      - missing_product_identity
      - evidence_provider_unavailable
    fail_when:
      - active_recall
      - certificate_mismatch
      - condition_out_of_range
    source:
      authority: synthetic_fixture # production은 official 또는 manufacturer만 허용
      url: synthetic://baby-demo-v1/bath
      version: baby-demo-v1
      retrieved_on: '2026-09-14'
```

검증기 규칙:

- `rule_id`는 전역적으로 고유하고 불변 버전을 포함한다.
- `slot_key`는 대상 슬롯 목록에 있어야 한다.
- `production` 범위의 규칙은 `official` 또는 `manufacturer` 출처, HTTPS URL, 버전,
  확인 날짜를 가져야 한다. 합성 URL이나 `synthetic_fixture` 출처는 허용하지 않는다.
- `synthetic_demo` 범위의 규칙은 `synthetic_fixture` 출처와 합성 dataset 버전을 가져야 한다.
- 빈 `required_claims`, 미래 확인 날짜, 출처 없는 `not_applicable`, 알 수 없는 상태 코드는
  설정 로드 단계에서 실패시킨다.
- 법적 적용 경로는 제품군 이름으로 추정하지 않는다. `safety_route` claim에는 해당 제품·옵션의
  분류 근거와 출처를 연결한다.

### 증빙 manifest

`data/baby/evidence/` 아래에 아래 형태의 versioned manifest를 둔다. 원문 파일은 같은
디렉터리의 `files/`에 두고 SHA-256을 기록한다. 실제 증빙 파일은 적절한 권한·라이선스가
확인된 경우에만 저장한다.

```yaml
schema_version: 1
scope: synthetic_demo
dataset_version: baby-demo-v1
records:
  - product_key: SYN-BATH-000122
    variant_key: SYN-BATH-000122-V1
    slot_key: bath
    claims:
      - claim_key: product_identity
        value: {manufacturer: '가상브랜드_도담', model: 'SYN-BATH-000122'}
        source: {authority: synthetic_fixture, url: synthetic://..., version: baby-demo-v1}
        file: files/SYN-BATH-000122.json
        sha256: '<64 lowercase hex>'
        retrieved_on: '2026-09-14'
        verified: true
      - claim_key: safety_route
        value: {route: synthetic_demo_only}
        source: {authority: synthetic_fixture, url: synthetic://..., version: baby-demo-v1}
        file: files/SYN-BATH-000122.json
        sha256: '<same hash>'
        retrieved_on: '2026-09-14'
        verified: true
      - claim_key: recall_status
        value: {status: no_active_recall}
        source: {authority: synthetic_fixture, url: synthetic://..., version: baby-demo-v1}
        file: files/SYN-BATH-000122.json
        sha256: '<same hash>'
        retrieved_on: '2026-09-14'
        verified: true
```

각 claim은 `product_key`, `variant_key`, `slot_key`, `scope`, source URL·버전·날짜,
원문 해시, 검토 상태를 가진다. manifest의 claim은 다른 제품 또는 옵션으로 추정 확장하지
않는다. production manifest는 `synthetic_demo_only` 같은 합성 route를 사용할 수 없다.

## 구현 순서

### 1. 레지스트리 로더와 전수성 검사

변경 파일:

```text
config/baby_verification_rules.yaml
src/rag/verification.py
tests/test_baby_verification_rules.py
```

1. `load_baby_verification_rules()`를 구현해 YAML의 스키마·중복·출처·날짜를 검사한다.
2. 필요 품목 YAML을 읽어 대상 슬롯 전체가 레지스트리에 있는지 검사한다. 데이터 공백인
   clothing은 별도로 허용한다.
3. 기존 `MANUAL_RULE_INVENTORY`와 `REVIEWED_NOT_APPLICABLE`을 새 레지스트리의 호환
   뷰로 바꾸거나 제거한다. 두 경로가 서로 다른 pass 결론을 만들면 안 된다.
4. 테스트는 누락 슬롯, 중복 rule_id, production 규칙의 합성 출처, 비어 있는 claim 목록,
   잘못된 날짜를 거부해야 한다.

### 2. 증빙 manifest 검증·적재기

변경 파일:

```text
scripts/import_baby_evidence.py
scripts/seed_baby_synthetic_evidence.py
src/repo/material_repo.py
src/repo/product_repo.py
tests/test_baby_evidence_import.py
data/baby/evidence/synthetic-demo-v1.yaml
```

1. `import_baby_evidence.py --manifest PATH --scope production|synthetic_demo`를 구현한다.
2. 원문 파일의 SHA-256, source URL, 날짜, 제품·옵션 존재 여부, slot 일치 여부를 검증한 뒤
   material/evidence/product_fact를 한 트랜잭션으로 연결한다.
3. 이미 같은 파일 해시·source version·claim·제품·옵션 조합이 있으면 재사용한다. 다른
   파일 해시나 source version은 새 revision으로 적재한다.
4. `seed_baby_synthetic_evidence.py`는 `catalog_demo_v1.json`과
   `generated/synthetic_manuals/catalog_demo_v1_r1/`을 입력으로 삼는다. 스크립트가 가상의
   안전 평가를 실제 증빙으로 바꾸어 기록해서는 안 되며, 모든 레코드에 합성 scope를 남긴다.
5. slot별로 검증된 pass fixture 한 건, missing evidence 또는 active recall fixture 한 건을
   명시적으로 만든다. fixture를 테스트에서 직접 `CandidateCheck(pass)`로 주입하지 않는다.

### 3. 공통 판정기와 품목 조건 판정기

변경 파일:

```text
src/engine/stage3c_verify.py
src/rag/verification.py
src/dto.py
tests/test_baby_verification.py
```

`verify_baby_candidate()`를 다음 순서로 구현한다.

1. 후보의 corpus를 `synthetic` 또는 실제 corpus에서 scope로 변환한다. scope가 규칙·증빙과
   다르면 `scope_mismatch` unknown이다.
2. 후보의 product/variant/market이 manifest claim 범위와 일치하는지 확인한다. 불일치는
   `identity_mismatch` fail, 식별 누락은 `missing_product_identity` unknown이다.
3. 현재 게시 상태·파일 해시·출처 철회 상태를 재확인한다. 제공자 없음과 검색 실패는
   `evidence_provider_unavailable`, `evidence_provider_failed`로 구분한다.
4. 공통 `recall_status`를 확인한다. 활성 회수는 항상 `active_recall` fail이다.
5. 각 규칙의 `required_claims`와 조건 claim을 검사한다. 하나라도 미확인인 경우
   `missing_rule_evidence` unknown이다.
6. 연령·체중·독립 착석·피부 조건처럼 규칙이 실제로 요구한 사용자 입력이 없으면
   `missing_verification_input` unknown이다. 입력을 요구하지 않는 품목에 좌석 규칙을
   재사용하지 않는다.
7. 모든 필수 검사가 pass일 때만 `eligibility=pass`, `selection_allowed=true`를 반환한다.

모든 검사 결과는 아래 형태로 `CandidateCheck.issues`에 넣는다.

```json
{
  "schema_version": 1,
  "rule_key": "baby.bath.evidence.v1",
  "rule_version": "v1",
  "target": {"candidate_id": "...", "requirement_id": "...", "item_id": null},
  "status": "pass|unknown|fail",
  "severity": "info|warning|critical",
  "reason": "missing_rule_evidence",
  "measured": {},
  "threshold": {},
  "evidence_ids": ["..."]
}
```

### 4. v3 저장·결과·편집 경로 통합

변경 파일:

```text
src/repo/engine_repo.py
src/services/recommendation_service.py
src/services/list_service.py
src/schemas.py
frontend/js/pages/results.js
tests/test_baby_recommendation_http.py
tests/test_result_interaction.py
tests/test_list_service.py
```

1. `persist_candidate_check()`는 `issues` JSON 배열에 target·reason·evidence refs를 함께
   저장한다. `engine.validation_target`, `candidate_evidence`, `validation_evidence`를 호출하거나
   새 migration으로 복원하지 않는다.
2. `get_stored_result()`는 저장된 `issues`만 읽어 `missing_requirements`의
   `reason_code`, `message`, `next_action`, `evidence_scope`를 구성한다. GET에서 provider를
   호출하지 않는다.
3. `synthetic_demo` pass가 있는 결과에는 최상위 `verification.synthetic_verification_only=true`
   와 사용자용 합성 안내를 넣는다. production 결과에는 false 또는 생략한다.
4. `patch_item`, 후보 교체, 확정은 모든 필수 check가 현재 pass인지 다시 검사한다. 합성
   evidence를 production candidate에 붙였거나 증빙이 철회된 경우 선택·확정을 거절한다.
5. 프런트는 빈 바구니 성공 문구를 보이지 않고, 원인별 다음 행동을 표시한다. 합성 결과를
   실제 인증으로 표현하지 않는다.

### 5. 기본 합성 성공 시나리오

변경 파일:

```text
scripts/setup_baby_demo.py
tests/test_baby_recommendation_http.py
tests/test_baby_optimizer.py
tests/test_baby_browser_flow.py  # 기존 브라우저 도구가 있을 때만 추가
```

1. `setup_baby_demo.py`는 migrate → 카탈로그 seed → 합성 evidence seed 순서로 멱등 실행한다.
2. `bath` 성공 사례는 30개월·목욕·위생·특이사항 없음·보유 없음·30만원으로 실행한다.
   선택 품목 하나 이상, 수량·합계 일치, 재조회 보존을 확인한다.
3. 각 슬롯에 대해 one-pass/one-blocked 테스트를 작성한다. blocked case는 규칙·증빙 제거가
   아니라 별도 missing/recall fixture를 사용한다.
4. 기저귀, bath, car_seat의 blocked/조건 불충족 사례와 실제 예산 초과 사례를 분리한다.
5. 로그인 후 장바구니 인계, 담기·빼기·수량 변경, 확정·리포트는 pass 후보로만 실행한다.

## 테스트 명령

다음은 전용 DB에서만 실행한다. 예시의 DB 이름을 실제 disposable DB로 바꾼다.

```bash
export DATABASE_URL='postgresql://truefit:truefit@127.0.0.1:5432/truefit_baby_rules_test?sslmode=disable'
export RAG_TEST_DATABASE_URL="$DATABASE_URL"
export RAG_EMBEDDING_PROVIDER=local-test

uv run python db/setup_all.py
uv run python scripts/seed_baby_catalog.py --corpus synthetic --dataset-version baby-demo-v1
uv run python scripts/seed_baby_synthetic_evidence.py --dataset-version baby-demo-v1

uv run python -m pytest -q \
  tests/test_baby_verification_rules.py \
  tests/test_baby_evidence_import.py \
  tests/test_baby_verification.py \
  tests/test_baby_optimizer.py \
  tests/test_baby_recommendation_http.py \
  tests/test_result_interaction.py \
  tests/test_list_service.py
```

브라우저 검증은 위 DB를 사용하는 서버에서 수행한다. API 응답을 대체하거나 DB의 selected
플래그를 직접 바꾼 실행은 성공 증거가 아니다.

## 보고서 형식

`docs/reports/baby-verification-rules-YYYY-MM-DD.md`에 아래를 기록한다.

```yaml
scope: synthetic_demo | production | mixed
rule_coverage:
  required_slots: []
  configured_slots: []
  missing_slots: []
evidence_coverage:
  pass_candidate_count_by_slot: {}
  blocked_candidate_count_by_slot: {}
  reasons_by_slot: {}
tests:
  command: actual command
  result: pass | fail | skipped
browser:
  bath_case: pass | fail | not_run
  diaper_case: pass | fail | not_run
production_readiness: blocked | partial | ready
remaining: []
```

production 근거가 아직 없다면 `production_readiness: blocked`로 기록한다. 합성 시나리오가
통과해도 이를 실제 상품 안전 검증 완료로 보고하지 않는다.

## 금지 사항

- 검토 근거 없이 슬롯을 `REVIEWED_NOT_APPLICABLE`에 추가하지 않는다.
- `unknown`을 UI 또는 서비스 계층에서 `pass`로 치환하지 않는다.
- 합성 source, 합성 certificate, 합성 claim을 production 후보에 연결하지 않는다.
- 삭제된 `rag` 스키마·`engine.validation_target`·구 테이블을 복원하지 않는다.
- 제품명 유사도나 판매처 제목만으로 제조사 모델·옵션을 추정 매핑하지 않는다.
- 테스트 fixture의 직접 pass 주입을 일반 추천 성공 근거로 사용하지 않는다.
