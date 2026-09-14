---
task_id: "P8"
status: "develop_alignment_required"
entry_gate: "ready_after_dependencies"
depends_on: ["P0", "P6"]
contract_version: 3
report_path: "docs/agent-tasks/baby/reports/P8.md"
---

# P8 — 유아 후기·파일 기반 정제·요약/통계·행동 기록

## ACTIVE DB CONTRACT — develop `da79839` / v3 (2026-09-13)

이 절과 [develop 전환 계약](DEVELOP_DB_TRANSITION.md), [목표 스키마](schema-v1.md)가 현재 실행 지시다. 이 문서 아래 기존 지시 중 충돌하는 DB 매핑·pgvector 유지·완전 축소 SR 승인 조건은 폐기한다. DB와 무관한 업무 규칙·API·수용 사례는 유지한다. 과거 보고서의 통과 결과는 당시 코드의 증거이며 develop 호환 완료를 뜻하지 않는다. 현재 작업 트리는 `rag`이므로 develop SQL이 이미 병합되어 있다고 가정하지 않는다. `개발 역할 분담`은 적용하지 않는다.

### P8 DELTA — 후기 버전·출처 구조 보존

- **상태/재사용:** 파일 정제·PC 리뷰 요약/관측 분석은 DB 설계와 무관한 부분을 재사용한다. P0/P6 후 유아 저장/조회 adapter를 구현하고 P5/P7 이벤트 통합은 마지막에 검증한다.
- **EDIT:** `src/repo/review_repo.py`, `src/services/{review,feedback}_service.py`, 리뷰 적재/요약 fixture.
- **IMPLEMENT:** community.review는 작성자/대상/현재 버전만 관리하고 본문·평점·검수·게시 시각은 review_revision에 저장한다. domain_version_id는 해당 유아 규칙 버전으로 참조한다. 통합 review_component를 새로 요구하거나 PC build/version/component 테이블을 삭제하지 않는다. 유아 사용 문맥은 review_revision.usage_context를 활용한다.
- **IMPLEMENT:** evidence.source와 review_subject/summary/aggregate/member를 유지한다. author_ref/review_posted_at의 develop 메타데이터를 유지하고 PC 집계와 유아 집계를 domain/version/subject로 분리한다. 현재 승인된 revision만 공개·집계한다. dataset SQL은 복원하지 않고 파일로 정제 데이터를 관리한다. feedback_event는 실제 run/revision/candidate 범위를 검사하고 현재 develop 컬럼에 저장한다.
- **ACCEPTANCE D8:** 후기 작성→수정 버전→승인 게시→요약/집계→철회 후 비공개; 다른 사용자의 수정 거부; PC/유아 집계 분리; 추천/편집/확정 행동 기록 연결; 기존 PC 요약 API 유지. 기존 정제 알고리즘의 변화 없는 테스트는 반복하지 않는다.
- **HANDOFF:** 관계 저장 예시·HTTP 확인 방법·D8 결과를 `reports/P8.md`에 기록한다.

## PREVIOUS WORK ORDER — non-conflicting business rules only

이하의 날짜별 상태·구 DB 구현 실적은 과거 기록이다. 현재 상태는 위 절과 manifest를 사용한다. 아래 지시에서 완전 축소 SQL 실행, pgvector 보존, planning.item 복원, domain_version/plan_node/purchase_line 삭제, 근거 객체 저장, shared/notification 스키마 삭제를 요구하는 부분은 실행하지 않는다.

## CURRENT BASELINE / SYNC DELTA (2026-09-13)

Read [integration audit](reports/sync-2026-09-13.md); this delta overrides obsolete baseline assumptions below.

- GET review summary and PC observation/ranking/explanation are now implemented; authoring/publishing and feedback remain outstanding. PC ItemOut.review=null is intentional, not evidence that the summary service is absent.
- Keep new ProductRepo/shared catalog identifiers but scope baby review subjects to correct option/corpus. P0 dataset/community/evidence consolidation is still incomplete.
- P5/P7 are existing execution extensions, so integrate events there rather than creating a duplicate recommend handler. Current missing feedback producers are not solved by upstream PC path.

## COMMIT DELTA — `30af559..d96ccd2` (2026-09-13)

- Reuse ProductRiskStore, SuspectCountFile, relation_axis, review_cleanse_worker, key resolution and GET /reviews/summary/{product_key}. Read docs/review_module_handoff.md for technical contracts only; ignore its role assignments and its suggestion to replace applied migration files.
- Preserve public ReviewSummaryOut names (`total_count`, `rating_raw`, `summaries`, `data_notice` and nullable unavailable statistics). Observed PC data and `synthetic_demo` remain separate; no invented refined rating/exclusion count. Authoring/publish/pending handlers are still stubs; telemetry validation/helper is not a persisted review workflow.
- Runtime PC risk file data/amazon23/pcparts_product_risk.json is ignored by git and not guaranteed installed. Missing, malformed, truncated or wrong-control-scope input must remain unavailable with explicit reason. Never download the large corpus merely to validate documentation or substitute PC/English observations for Korean baby evidence.
- Remaining implementation: adapt file reader/importer to versioned baby corpus and correct option IDs; implement merged-row authoring/publish/telemetry storage, reviewed membership aggregates, and feedback producers/consumer acceptance. Keep unreviewed signals separate from exclusion decisions. The existing PC heuristic ranking does not waive baby IMPLEMENTATION6.
- Existing regression command: `uv run python -m pytest -q tests/test_relation_axis.py tests/test_rank_review_axis.py tests/test_review_summary_api.py tests/test_review_telemetry.py tests/test_review_trace.py tests/test_risk_store_states.py tests/test_stage5_review_line.py tests/test_suspect_counts.py`. After router conflict resolution, GET /reviews/summary/amd-ryzen-5-5600 must return the public shape with demo/provenance separation. Add RV01–RV04/FB01–FB03 baby checks; PC regression success alone is not P8 completion.

## EXECUTION

Implement this task, not a plan-only response. Read [CONTRACTS.md](CONTRACTS.md) first. Repository root is `/home/ubuntu/skn_final` in the authoring environment; resolve paths from the actual checkout. Ignore `개발 역할 분담`. This is a continuation work order; inspect and reuse existing upstream/stash implementations, then implement missing acceptance behavior. Verify dependency reports against current code before proceeding.

## READ FIRST

- `src/routers/reviews.py`
- `src/services/review_service.py`
- `src/repo/review_repo.py`
- `src/repo/dataset_repo.py`
- `src/workers/review_cleanse_worker.py`
- `src/workers/feedback_batch.py`
- `src/engine/stage6_feedback.py`
- `데이터_구조_설계_근거.md`
- `프로젝트_기획서_v2.md`
- `frontend/js/pages/results.js`

## EDIT SURFACE

- `src/routers/reviews.py`
- `src/services/review_service.py`
- `src/repo/review_repo.py`
- `src/workers/review_cleanse_worker.py`
- `src/services/feedback_service.py (consume existing P5 helper if present)`
- `scripts/import_review_analysis.py (new)`
- `scripts/evaluate_review_signals.py (new)`
- `config/review_analysis_v1.json (new)`
- `tests/test_baby_reviews_http.py (new)`
- `tests/test_review_analysis_files.py (new)`
- `tests/test_feedback_events.py (new)`
- `docs/review_analysis_contract.md (new)`

Shared-file changes follow CONTRACTS dependency protocol. Do not overwrite unrelated code; preserve PC regression behavior.

## OBJECTIVE / BOUNDARY

Implement authenticated baby reviews, deterministic ingestion of reviewed analysis files, separate text summaries/statistics, and append-only feedback. Research evaluation is a distinct output: no guaranteed detector quality, no invented measured accuracy. P5/P7 event producer integration is a final acceptance dependency for FB03, but not for review API development; manifest lists integration gates separately.

## API

- GET /reviews/pending → owned reviewable subjects with stable IDs, no fake purchases inferred from outbound clicks.
- POST /reviews/part {variant_id,rating,title,body,axis_scores,usage_context?} →201 {review_id,status:draft}.
- POST /reviews/{review_id}/publish →200 review state, owner required; merged review body, no review_revision writes.
- GET /reviews/summary/{product_key} → frontend ReviewSummary or explicit no-analysis state. Optional variant scope must not mix unrelated options. Public response contains total_count, excluded_count/ratio, raw/refined ratings and distributions, summaries[{text,source,observed_at}],data_notice,analysis_version,status.
- Existing /reviews/build remains PC-specific behavior; do not redirect baby to a fake PC build. Add explicit generic subject support only if needed with P0 community schema, retain tested PC compatibility.

## FILE CONTRACT / PROCESSING

Research artifacts outside RDB, versioned CSV/JSON(L). Define schema in docs/review_analysis_contract.md:

```text
manifest: schema_version,dataset_version,corpus,language,domain,generated_at,
  files[{path,sha256,record_count}],label_definition_version,split_policy
sample: sample_id,parent_sample_id?,product_key,variant_key?,rating,reviewer_id?,
  created_at?,text_or_excerpt?,text_hash,source_ref,is_synthetic,split
label: sample_id,label,review_status(pending|approved|rejected),reviewer_ref?,
  method_version,observations[],confidence?
analysis: subject_key,source_scope,analysis_version,input_hash,summary_texts[],
  total_count,excluded_count,raw_distribution,refined_distribution,
  observation_evidence[],review_status
```

Use approved/permissioned local inputs. Third-party text policy from source docs still applies; no wholesale copied external corpus committed. Small synthetic fixtures allowed and labeled. Opaque reviewer identifiers, no emails/private conversations in analysis outputs.

## IMPLEMENTATION

1. Implement ReviewSubjectRepo exact subject matching and user ownership. rating integer1..5, configured length bounds, axis schema whitelist. Store review domain=baby and body/attributes in merged row. Publishing is idempotent; edits invalidate affected summary/aggregate until recomputed, not silently keep stale values.
2. Implement file schema/hash validation and deterministic import CLI. Reject duplicate sample IDs with differing content, missing label refs, impossible rating/count/distributions, unapproved analysis, mixed corpus. Same content/version import idempotent. Transactions atomically replace/current-mark summary + aggregate + aggregate_members, while preserving provenance.
3. Keep review_summary text and review_aggregate numeric distribution separate. Compute raw average from raw counts, refined average from explicitly retained membership. No retained rows→null rating, not zero/5 stars. Distribution sums1 when denominator>0. Show stale/unavailable state and timestamp/version.
4. Supply a transparent research baseline using available metadata: per-product time concentration, reviewer repetition and duplicate content observations. Version features/thresholds in config. Missing metadata yields feature unavailable, not benign. Output inspectable observations, not automatic “AI-generated” labels; text-only signal does not automatically delete/downrank.
5. Evaluation: approved labels only; group parent/author/campaign/product-derived leakage units across splits, fixed seed; report confusion matrix, FPR, detection rate at target FPR1% when sample size supports it. No sufficient independent negatives/labels→not_evaluated with required sample count rationale; never transfer PC/English results as Korean baby validity. Include synthetic test evaluation distinctly from real quality evidence.
6. Service ranking consumes published inspected analysis; suspicious signal alone is review queue priority. Approved analysis specifies membership for refined statistics; never convert unreviewed heuristic into automatic exclusion. No valid analysis→null review contribution for P4.
7. Feedback API is internal helper, not arbitrary client event writer. Payload whitelist IDs/action/version/reason code; no body/email/token/private note. Event types shown/replaced/removed/confirmed; immutable/idempotent. If P5 helper exists extend/test it, do not create duplicate producer. Automatic retraining worker stays inactive; event existence is not learning.

## ACCEPTANCE

- RV01 own draft→publish→summary after approved import, other user cannot publish; invalid rating/subject rejected; review update marks analysis stale.
- RV02 raw ratings [5,5,1], approved excluded sample third → raw11/3, refined5, excluded1/3, distributions computed correctly; all excluded→refined null.
- RV03 file hash tamper, unknown sample label, unapproved label, duplicate divergent row rejected; import twice no duplicate statistics; text summary stored separately from aggregate/members.
- RV04 mixed real/synthetic not silently combined; absent data means analysis unavailable, not fabricated count. Research report states split/metrics/limitations and avoids leakage.
- FB01 internal helper duplicate idempotency key→one event; arbitrary private payload rejected.
- FB02 existing events cannot be modified through service; no automatic training job launched.
- FB03 after P5/P7 integration, shown/replaced/removed/confirmed emitted exactly once; GET and failed confirmation emit none. Until integration tested report this case pending, not full P8 completion.

## VERIFY

```bash
uv run python -m pytest -q tests/test_baby_reviews_http.py tests/test_review_analysis_files.py tests/test_feedback_events.py
uv run python scripts/import_review_analysis.py --manifest tests/fixtures/reviews/approved_demo/manifest.json
uv run python scripts/evaluate_review_signals.py --manifest tests/fixtures/reviews/approved_demo/manifest.json --output generated/reviews/evaluation.json
```

Create the small fixture paths/CLI flags as deliverables. Persist raw/refined expected calculations, file hashes, leakage split checks and actual event SQL. Do not claim real detection performance from fixture pass.

## EXIT

All acceptance cases below must have real observed results. Write the completion report specified in CONTRACTS. Update the parent status document only for behavior actually verified. If a dependency or external gate remains unmet, report partial/blocked with its exact failing check; do not replace it with a fixed successful response.
