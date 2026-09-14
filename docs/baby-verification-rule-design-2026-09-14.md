# 유아용품 전 품목 검증 규칙 설계

## 목적

유아용품 추천의 `pass`는 “모든 안전성을 보증한다”는 뜻이 아니라, **해당 품목에
등록된 적용 규칙과 증빙을 현재 조건에서 통과했다**는 뜻으로 한정한다. 규칙·증빙·적용
판정 중 하나라도 없으면 `unknown`이며 자동 선택하지 않는다.

합성 카탈로그의 통과는 `synthetic_demo` 범위에서만 유효하다. 실제 상품, 운영 화면,
외부 판매처 이동에는 제조사 문서와 공식 조회 결과를 갖춘 `production` 범위의 증빙이
필요하다. 합성 통과 결과에는 화면과 API에 `synthetic_verification_only=true`를 남긴다.

## 대상 품목 레지스트리

`config/baby_verification_rules.yaml`을 새 규칙 원본으로 둔다. 각 항목은 다음 메타데이터를
필수로 갖는다.

```yaml
rule_id: baby.bath.identity-and-evidence.v1
slot_key: bath
scope: [synthetic_demo, production]
applies_when: {market: KR}
requires:
  - product_identity
  - source_document
  - applicable_safety_route
pass_when: all_required_checks_pass
unknown_when: [missing_source, missing_product_identity, provider_unavailable]
fail_when: [recall_active, certificate_invalid, condition_out_of_range]
source:
  authority: official | manufacturer | synthetic_fixture
  url: https://...
  retrieved_on: 2026-09-14
  version: ...
```

등록 대상은 필요 품목 전체인 `bottle`, `formula`, `high_chair`, `baby_food`, `crib`,
`sleepwear`, `stroller`, `car_seat`, `bath`, `skincare`, `diaper`, `wipes`, `mat`, `gate`,
`thermometer`이다. `clothing`은 `data_gap`으로 유지하며, 카탈로그와 규칙·증빙이 모두
생긴 뒤에만 대상에 추가한다.

각 규칙은 세 층으로 조합한다.

| 층 | 모든 품목에 적용 | 통과에 필요한 증빙 |
|---|---|---|
| 식별·추적 | product/variant/제조사·모델·판매처 관측 일치, 활성 회수 없음 | 제품 식별 정보, 회수 조회 결과와 날짜 |
| 적용 경로 | 해당 제품이 어떤 안전관리·별도 법령·비대상 경로인지 확인 | 공식 분류 원문 및 확인 날짜 |
| 품목 조건 | 해당 품목·옵션의 인증/설명서/사용 조건 대조 | 인증 또는 적합성 정보, 제조사 설명서, 조건별 원문 |

`bath`, `bottle`, `diaper`, `wipes`처럼 제품군 이름만으로 적용 제도를 단정할 수 없는
품목도 있다. 이 경우 `applicable_safety_route` 자체가 검증 항목이다. 공식 분류 원문이
특정 제품·옵션의 경로를 뒷받침하지 않으면 `unknown`으로 남긴다. 비적용은 출처와 제품
분류가 모두 있는 `not_applicable` 규칙으로만 통과한다.

## 증빙 데이터 계약

카탈로그의 제품·옵션마다 아래 구조를 `evidence`와 `catalog.product_fact`에 연결한다.

```json
{
  "product_key": "manufacturer-model",
  "variant_key": "colour-size",
  "claim_key": "safety_route_or_certificate",
  "value": "...",
  "authority": "official|manufacturer|synthetic_fixture",
  "source_url": "https://...",
  "source_version": "...",
  "retrieved_on": "YYYY-MM-DD",
  "verified": true,
  "scope": "production|synthetic_demo",
  "evidence_ref": "immutable evidence id"
}
```

`verified=true`은 사람이 원문과 제품 식별자를 대조한 뒤에만 설정한다. 제공자 오류,
제품 식별 불일치, 만료·철회된 문서, 없는 인증번호는 `unknown` 또는 `fail`이고 pass로
대체하지 않는다. 실제 상품에는 합성 증빙을 결합할 수 없다.

## 판정기

현재 `verify_baby_candidate()`의 유모차 전용 분기를 규칙 레지스트리 기반으로 바꾼다.

1. 후보의 `slot_key`, `corpus`, 시장, 제품·옵션 식별자로 적용 규칙을 찾는다.
2. 규칙의 출처와 제품별 증빙을 다시 확인한다. 검색 제공자 오류와 근거 부재를 분리한다.
3. 공통 회수 검사를 수행하고, 품목별 인증·설명서·조건 검사를 수행한다.
4. 각 검사마다 `{rule_id, rule_version, status, reason_code, target, evidence_refs}`를
   `engine.validation_result.issues`에 저장한다.
5. 모든 필수 검사가 pass일 때만 `selection_allowed=true`를 만든다. 결과 DTO에는
   품목별 차단 사유와 다음 행동을 그대로 전달한다.

현재 v3 DB에는 `engine.validation_target`이 없으므로 후보·필요 품목 연결은
`issues[].target` JSON으로만 저장한다. 새 테이블을 복원하지 않는다.

## 자료 준비와 롤아웃

1. **공식 분류 수집**: 각 제품군의 적용 경로를 국가기술표준원/법령 원문에서 수집하고,
   URL·문서 버전·확인 날짜·품목 매핑을 검토한다. 어린이제품 안전 특별법 시행규칙은
   대상 종류와 적용 기준을 별표로 정하므로, 분류 근거는 이 원문과 연결한다.
2. **제품별 증빙 수집**: 실제 카탈로그의 제조사 모델·옵션에 인증 또는 적합성 정보,
   제조사 설명서, 회수 상태를 연결한다. 모델을 식별할 수 없는 판매처 행은 unknown이다.
3. **합성 fixture**: 기본 개발 카탈로그의 15개 슬롯 각각에 명시적
   `synthetic_fixture` 규칙과 자료를 넣는다. 이 자료는 “합성 검증”임을 표시하고 운영
   카탈로그와 섞지 않는다. 정상 시나리오에는 각 필수 슬롯마다 최소 하나의 pass 후보와
   하나의 unknown/fail 후보를 포함한다.
4. **검토 게이트**: 규칙 파일은 source URL·날짜·버전·적용 범위·pass/fail/unknown 조건이
   모두 있어야 로드한다. CI는 필요 품목 전체에 규칙이 있는지, fixture 증빙이 실제
   candidate와 연결되는지 검사한다.
5. **운영 전환**: 실제 상품의 production 증빙 비율과 unknown 원인을 리포트한다. 모든
   필수 품목에 실제 증빙이 준비되기 전에는 합성 추천을 운영 안전 추천으로 표시하지 않는다.

## 제품별 증빙 연결 실행 계획

### 1. 카탈로그 식별 정리

각 판매 후보를 증빙을 연결할 수 있는 단위로 정규화한다. `product_key`는 제조사 모델,
`variant_key`는 색상·규격·용량처럼 인증 또는 설명서 적용 범위를 바꿀 수 있는 옵션을
나타낸다. 판매처의 임의 제목, URL, 가격만 있는 행은 증빙 연결 전까지 추천 후보로는
수집하되 자동 선택하지 않는다.

| 산출물 | 최소 필드 | 거부 조건 |
|---|---|---|
| 제품 식별 레코드 | 제조사, 모델명, product_key, variant_key, 시장 | 제조사·모델을 분리할 수 없음 |
| 판매처 관측 | 판매처 URL, 관측 시각, 가격, 재고, variant_key | 다른 모델·옵션으로의 추정 매핑 |
| 증빙 연결 | evidence_id, claim_key, 제품·옵션 범위, 출처·버전·확인일 | 식별 범위 밖의 증빙 재사용 |

한 제조사 모델의 여러 옵션에 같은 증빙이 적용될 때에도, 증빙에는 적용 옵션 범위를 명시한다.
옵션별 인증번호나 사용 조건이 다르면 별도의 evidence 행을 만든다.

### 2. 품목별 증빙 수집 패키지

각 슬롯은 아래 패키지를 모두 갖춰야 production `pass` 후보를 만들 수 있다. 실제 적용
제도가 없는 제품도 공식 분류 원문과 제품 분류가 있어야 `not_applicable`으로 판정할 수 있다.

| 슬롯 | 필수 증빙 패키지 | 조건 증빙 예 |
|---|---|---|
| bottle, formula, baby_food, cup, bib | 제품 식별, 적용 경로, 제조사 사용·재질 문서, 회수 상태 | 용량·재질·권장 사용 범위가 옵션과 일치 |
| high_chair, crib, stroller, car_seat, bath, gate | 제품 식별, 적용 경로, 해당 인증·적합성 정보, 제조사 설명서, 회수 상태 | 연령·체중·설치·포함 구성품 조건 |
| sleepwear, diaper, wipes, skincare, mat | 제품 식별, 적용 경로 또는 비대상 근거, 성분·재질 또는 제조사 문서, 회수 상태 | 피부·향료·사이즈·사용 대상 조건 |
| thermometer | 제품 식별, 적용 경로, 해당 인증 또는 적합성 정보, 제조사 설명서, 회수 상태 | 측정 방식·사용 대상·의료기기 해당 여부 |

표는 필요한 증빙 범주를 정의할 뿐, 특정 품목이 어떤 법적 제도에 반드시 속한다고 단정하지
않는다. 실제 적용 경로는 수집 단계에서 공식 원문과 제품의 정확한 분류로 확정한다.

### 3. 수집과 검토 워크플로

1. **후보 등록**: 수집기가 판매처·제조사 URL과 제품 식별 정보를 `pending`으로 저장한다.
2. **원문 확보**: 공식 분류 원문, 공식 인증 조회 결과, 제조사 설명서를 파일로 보관하고
   SHA-256·URL·확인 날짜·문서 버전을 기록한다. 웹 화면만 보고 인증번호를 추정하지 않는다.
3. **식별 대조**: 검토자가 문서의 제조사·모델·옵션과 카탈로그의 `product_key`·`variant_key`를
   대조한다. 하나라도 불명확하면 `identity_mismatch` 또는 `missing_product_identity`로 남긴다.
4. **적용성 결정**: 규칙의 `applies_when`과 공식 분류 원문을 대조해 `applicable`,
   `not_applicable`, `unknown` 중 하나를 기록한다. `not_applicable`에는 근거 원문을 필수로
   연결한다.
5. **증빙 게시**: 검토 완료된 파일과 claim만 `published` 상태로 전환한다. 이때
   `evidence_id`를 product/variant/claim 범위에 연결한다.
6. **추천 재검사**: 추천 실행과 확정 직전에 evidence의 게시·철회 상태, 파일 해시,
   product/variant 범위를 다시 검사한다. 철회·변경된 증빙으로는 자동 선택·확정을 허용하지 않는다.

### 4. 적재 경로와 멱등성

`scripts/import_baby_evidence.py`를 일반 적재 진입점으로 둔다. 입력은 제품 식별 파일과
증빙 manifest를 분리하며, 다음 검사를 통과해야 한다.

```yaml
product_key: manufacturer-model
variant_key: size-or-colour
claims:
  - claim_key: applicable_safety_route
    scope: production
    authority: official
    source_url: https://...
    source_version: ...
    retrieved_on: YYYY-MM-DD
    file: evidence/source.pdf
    applicability: {market: KR}
```

파일 해시와 `source_url`·버전·제품·옵션·claim 조합이 같으면 기존 published evidence를
재사용한다. 어느 하나라도 달라지면 새 material/evidence revision을 만들며 과거 결과를
덮어쓰지 않는다. 누락 파일, 해시 불일치, 미래 날짜, 유효하지 않은 URL, 적용 범위 없는
claim은 적재를 실패시킨다.

### 5. 합성 개발 증빙

`scripts/seed_baby_synthetic_evidence.py`는 기본 합성 카탈로그의 각 15개 슬롯에 대해
검증 fixture와 evidence를 적재한다. 이 스크립트는 다음을 보장한다.

- 모든 evidence와 후보에 `scope=synthetic_demo`, `is_synthetic=true`를 설정한다.
- 슬롯마다 pass 후보 하나 이상, unknown 또는 fail 후보 하나 이상을 만든다.
- 생성된 설명서의 해시와 candidate의 product/variant를 실제로 대조한다.
- production corpus나 실제 판매처 후보에 합성 evidence를 연결하지 않는다.

합성 fixture의 pass는 “합성 규칙·합성 자료가 일치한다”는 개발 검증 결과이며 실제 제품
안전 인증이 아니다. API와 화면은 이 범위를 명시하고, production 환경에는 이 적재기를
실행하지 않는다.

### 6. 운영·품질 게이트

- CI는 필요 품목 15개 모두에 등록 규칙이 있는지, production 규칙에 공식 출처가 있는지,
  synthetic evidence가 production 후보에 연결되지 않는지 검사한다.
- 매 추천 실행은 rule/evidence 버전과 해시를 `validation_result.issues`에 기록한다.
- 만료·철회·회수 갱신은 해당 evidence를 unpublished 또는 revoked로 바꾸고, 이후 추천과
  확정에서 즉시 unknown/fail로 재평가한다. 이미 확정한 스냅샷은 변경하지 않는다.
- 운영 지표는 슬롯별 `pass/unknown/fail`, unknown 사유, 식별 실패율, 증빙 만료 예정 수,
  실제·합성 corpus 혼합 시도 수를 집계한다.
- 생산 배포 게이트는 각 필수 슬롯의 실제 pass 후보 수와 미해결 unknown 사유를 검토해
  승인한다. 합성 통과 수는 이 게이트의 대체 근거가 아니다.

## 검증 사례

- 각 슬롯의 자료를 갖춘 합성 후보는 일반 추천 경로에서 선택된다.
- 같은 슬롯에서 증빙을 뺀 후보는 `missing_evidence`로 선택되지 않는다.
- 회수·인증 불일치·조건 불충족·검색 제공자 실패는 각각 별도 코드로 남는다.
- `bath` 조건(30개월, 목욕·위생, 특이사항 없음, 보유 없음, 30만원)은 합성 fixture가
  적재된 전용 DB에서 최소 한 품목을 선택하고, 실제 자료 DB에서는 실제 증빙 유무에 따라
  pass 또는 unknown으로 재현된다.
- 저장 후 재조회, 채팅 담기, 수량 변경, 확정은 `selection_allowed`를 다시 검사한다.

## 근거

어린이제품 안전 특별법 시행규칙 제2조는 안전관리대상 어린이제품의 종류와 적용 안전기준을
별표로 정한다. 제품군·옵션마다 실제 적용 경로를 확인해야 하므로, 카탈로그의 임의 속성이나
가상 설명서를 공식 적합성 증빙으로 사용하지 않는다.
