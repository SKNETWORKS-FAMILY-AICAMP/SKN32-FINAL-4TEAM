# 리뷰 분석 파일 계약 (P8 v1)

RDB 밖 연구/정제 산출물의 파일 스키마와, 검수 승인된 분석을 `evidence.review_summary`/
`review_aggregate`/`review_aggregate_member`에 적재하는 규칙이다. `dataset.*` 스키마는
`0012_schema_reduction_safe_subset.sql`에서 이미 삭제됐고([schema-v1.md](agent-tasks/baby/schema-v1.md)),
연구 데이터는 파일로만 관리한다 — 이 문서가 그 파일들의 계약이다.

구현: [`scripts/import_review_analysis.py`](../scripts/import_review_analysis.py)(적재),
[`scripts/evaluate_review_signals.py`](../scripts/evaluate_review_signals.py)(평가),
고정 픽스처: [`tests/fixtures/reviews/approved_demo/`](../tests/fixtures/reviews/approved_demo/).

## 파일 4종

한 임포트 배치는 `manifest.json` 하나 + JSONL 파일 3개(샘플/라벨/분석)로 구성된다.
manifest가 각 파일의 상대 경로·sha256·record_count를 선언하고, 파일 역할은 각 행의
모양(샘플=`sample_id`, 라벨=`label`+`review_status`, 분석=`subject_key`)으로 판별한다 —
파일명 자체는 임의로 지어도 된다.

```text
manifest: schema_version, dataset_version, corpus(synthetic|real), language, domain,
  generated_at, files[{path, sha256, record_count}], label_definition_version, split_policy

sample: sample_id, parent_sample_id?, product_key, variant_key?, rating(1-5),
  reviewer_id?, created_at?, text_or_excerpt?, text_hash, source_ref, is_synthetic, split

label: sample_id, label(retained|excluded), review_status(pending|approved|rejected),
  reviewer_ref?, method_version, observations[], confidence?(0-1)

analysis: subject_key, variant_key?, source_scope(external|first_party|combined),
  analysis_version, input_hash, summary_texts[], total_count, excluded_count,
  raw_distribution{rating:fraction}, refined_distribution{rating:fraction},
  observation_evidence[], review_status(pending|approved|rejected)
```

`label.label`이 이 계약의 진위 판정값이다: `retained`=분석에 포함, `excluded`=몰림·다작
등 관측 지표로 제외. 개별 리뷰 원문(`text_or_excerpt`)은 있으면 저장하지만 필수는 아니다
(§15 외부 리뷰 원문 미저장 원칙과 별개로, 자체 승인 검수용 발췌는 짧게 보관할 수 있다 —
`evidence.review_summary.summary`는 2000자로 자른다).

## 검증 규칙 (위반 시 거부, 부분 적재 없음)

| 코드 | 조건 |
|---|---|
| `file_hash_mismatch` | manifest 선언 sha256 ≠ 실제 파일 |
| `file_record_count_mismatch` | manifest 선언 record_count ≠ 실제 JSONL 행 수 |
| `duplicate_sample_diverges` | 같은 `sample_id`가 다른 `text_hash`로 두 번 등장 |
| `unknown_sample_label` | 라벨이 존재하지 않는 `sample_id`를 가리킴 |
| `invalid_label_row` | `label` 또는 `review_status`가 허용값 밖 |
| `unapproved_analysis` | 분석 행의 `review_status != approved` — 그 subject는 통째로 거부(부분 배치 없음) |
| `mixed_corpus` | 분석에 포함되는 표본 중 `is_synthetic`이 manifest `corpus` 선언과 다른 것이 있음 |
| `impossible_counts` / `impossible_distribution` | analyzed ≠ excluded+retained, 또는 분포 합이 1이 아님(분모>0일 때) |
| `analysis_totals_mismatch` | 분석 행이 선언한 `total_count`/`excluded_count`/`*_distribution`이 승인된 표본에서 실제로 계산한 값과 다름 |

**미승인(`pending`/`rejected`) 라벨의 표본은 분석 모수(`analyzed_count`)에서 완전히
빠진다** — "0건"과 "아직 안 봄"은 다른 말이라 승인 대기를 0으로 채우지 않는다
(`test_rv04_pending_or_rejected_labels_are_excluded_from_analysis_not_counted_as_zero`).

## DB 저장 매핑

- 표본 하나(승인된 sample+label) → `evidence.review_summary` 한 행. `origin='external'`,
  `external_review_key=sample_id`, `processing_version=analysis_version`,
  `cleaning_status=label.label`. UNIQUE `(source_id, external_review_key,
  processing_version)`가 같은 파일 재적재의 자연스러운 멱등 키다.
- `evidence.source`는 임포트 배치당 하나, 이름 `review_analysis:<dataset_version>`,
  `source_type='derived'`로 get-or-create.
- subject별 분석 스냅샷 하나 → `evidence.review_aggregate` 한 행. `ratings` jsonb에
  `{raw_avg, refined_avg, raw_distribution, refined_distribution, summary_texts,
  observation_evidence}`를 담는다(스키마에 전용 컬럼이 없어 기존 jsonb 컬럼을 쓴다 —
  새 컬럼이 필요해지면 이 문서와 함께 갱신한다). `axis_scores`는 이 경로에서 비워 둔다.
- `evidence.review_aggregate_member`는 이 분석에 포함된 각 표본의 review_summary
  행을 disposition(retained/excluded)과 함께 잇는다.
- 같은 `(subject, domain_version, source_scope)`에 새 `processing_version`이 들어오면
  기존 `ready` 행을 `stale`로 내리고 새 행을 `ready`로 올린다(이력 보존, 덮어쓰지 않음).
  같은 버전을 내용까지 동일하게 재적재하면 아무 것도 새로 쓰지 않는다(멱등). 같은
  버전인데 계산 내용이 다르면 `aggregate_version_conflict`로 거부한다 — 버전 이름은
  그 내용의 식별자여야 한다.
- `GET /reviews/summary/{product_key}`는 `status='ready'`인 최신 행만 공개한다
  (`review_service._db_backed_analysis`) — `stale`/`revoked`는 노출하지 않는다.

## 평가 (`scripts/evaluate_review_signals.py`)

승인된 라벨만 정답으로 쓰고, leakage 단위(리뷰어 → 없으면 부모 표본 → 없으면 상품)가
서로 다른 split에 걸치면 평가 자체를 거부한다(`leakage_split_violation`). 클래스별
독립 leakage 단위가 5개 미만이면 confusion matrix/FPR을 내지 않고 `not_evaluated` +
필요 표본 수 근거를 낸다 — 표본이 적을 때 낸 숫자는 그럴듯해 보일 뿐 아무 것도
검증하지 않는다. `corpus=synthetic`인 평가 결과에는 항상 "실제 탐지 성능 증거 아님"
표기를 남긴다(PC/영어 실측 라벨 결과를 한국어 유아 리뷰에 전이하지 않는다는 원칙과
같은 이유).
