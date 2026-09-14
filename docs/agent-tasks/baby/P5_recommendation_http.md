---
task_id: "P5"
status: "develop_alignment_required"
entry_gate: "ready_after_dependencies"
depends_on: ["P1", "P2", "P3", "P4"]
contract_version: 3
report_path: "docs/agent-tasks/baby/reports/P5.md"
---

# P5 — 추천 실행·저장·결과·후보 편집 API

## ACTIVE DB CONTRACT — develop `da79839` / v3 (2026-09-13)

이 절과 [develop 전환 계약](DEVELOP_DB_TRANSITION.md), [목표 스키마](schema-v1.md)가 현재 실행 지시다. 이 문서 아래 기존 지시 중 충돌하는 DB 매핑·pgvector 유지·완전 축소 SR 승인 조건은 폐기한다. DB와 무관한 업무 규칙·API·수용 사례는 유지한다. 과거 보고서의 통과 결과는 당시 코드의 증거이며 develop 호환 완료를 뜻하지 않는다. 현재 작업 트리는 `rag`이므로 develop SQL이 이미 병합되어 있다고 가정하지 않는다. `개발 역할 분담`은 적용하지 않는다.

### P5 DELTA — 추천 실행·후보 편집 저장 전환

- **상태:** 기존 P5 보고서의 유아 실행 실적은 이전 DB 기준. develop DB와 P1~P4 계약으로 통합 재검증한다.
- **EDIT:** `src/services/recommendation_service.py`, `src/repo/engine_repo.py`, `src/routers/session.py`, `src/schemas.py`, 결과 화면 adapter, `tests/test_baby_recommendation_http.py`.
- **IMPLEMENT:** start_run은 revision.domain_version_id와 잠근 조건/규칙 snapshot을 저장한다. 202+BackgroundTasks→저장 결과 조회 흐름을 유지한다. 슬롯은 requirement→plan_node에서 읽는다. 후보 상태는 recommendation_candidate.selected/qty/timing에 저장하며 result(엔진 판정)와 selected(사용자 담기)를 혼용하지 않는다.
- **IMPLEMENT:** 유아 구매 행의 HTTP item_id는 requirement UUID로 안정화하고 adapter가 현재 run의 선택 candidate를 찾게 한다. 후보 교체는 같은 requirement의 candidate를 선택 상태로 전환하고 기존 선택을 해제한다. PC의 candidate 기반 item_id는 기존대로 보존한다. owned 행은 파생 ID로 반환하되 상품 교체/구매 편집 대상에서 제외하고 보유 조건 수정으로 안내한다. DB item 행을 새로 만들지 않는다.
- **IMPLEMENT:** 편집 트랜잭션에서 revision을 잠그고 If-Match/소유권/current run/requirement/candidate/관측값 범위를 검사→P3 확인→P4 재계산→candidate 상태와 lock_version 갱신. 동시 교체 시 슬롯당 구매 후보가 하나만 남도록 직렬화한다. 조건이 바뀐 실행의 완료는 stale 처리한다. 결과 새로고침은 DB 상태를 재구성한다.
- **IMPLEMENT:** provider 미설정/자료 없음은 reason/checks의 명시적 종료 상태로 반환하고 unknown 필수품을 자동 담지 않는다. PC 리뷰 순위·설명과 develop 결과 상호작용 API를 보존한다.
- **ACCEPTANCE D5:** 실제 DB/HTTP에서 생성→조건→202→완료 또는 이유 있는 비충족→편집→재조회; quantity/timing/selected 지속; 후보 교체에도 baby item_id 유지; 교차 run/목록 편집 거부; 동시 편집409; 실패 rollback; PC 결과 상호작용 회귀. P3-D3-02 미통과이면 검증 포함 유아 정상 추천 완료는 승인하지 않는다.
- **HANDOFF:** 요청/응답·저장 candidate 상태·run 버전·D5 결과를 `reports/P5.md`에 기록한다.

## PREVIOUS WORK ORDER — non-conflicting business rules only

이하의 날짜별 상태·구 DB 구현 실적은 과거 기록이다. 현재 상태는 위 절과 manifest를 사용한다. 아래 지시에서 완전 축소 SQL 실행, pgvector 보존, planning.item 복원, domain_version/plan_node/purchase_line 삭제, 근거 객체 저장, shared/notification 스키마 삭제를 요구하는 부분은 실행하지 않는다.

## CURRENT BASELINE / SYNC DELTA (2026-09-13)

Read [integration audit](reports/sync-2026-09-13.md); this delta overrides obsolete baseline assumptions below.

- Status: **PC path implemented, baby path not connected**. Preserve202 with actual BackgroundTasks. Canonical functions are start_recommendation, execute_recommendation, get_stored_result; do not restore deleted run_for_revision/get_result as a second engine.
- start_recommendation currently rejects category!=computer; add baby after P2–P4. Latest executor reads current conditions rather than start snapshot and keeps long DB transaction; fix for baby and shared correctness.
- Preserve current RecommendAcceptedOut/RecommendResultOut. Extend ItemOut with scoped evidence/coverage and revision/lock metadata compatibly; stash RecommendResult dict-shaped progress is obsolete.
- Handle duplicate-run race, stale transaction rollback, abandoned running after process restart, terminal checks pending forever and missing price0. BackgroundTasks is real execution but not durable queue; implement restart reconciliation or explicitly selected durable worker, no fake202.
- Real PC regression: seed51 products, request202, poll done8 items. The current source retrieves candidates from CSV; do not claim baby DB selection already exists.

## COMMIT DELTA — `30af559..d96ccd2` (2026-09-13)

- Preserve upstream `stage5_explain.run(..., rank=rank)` and `review_service.review_trace_steps/review_demotion_step/explanation_text_with_caveats` wiring: PC observations, demotions and caveats now reach stored reasoning_log/explanation_text. Do not overwrite them while adding baby execution.
- `ItemOut.review` remains null because observed counts do not establish excluded_ratio/rating_refined. The separate GET /reviews/summary/{product_key} is implemented; a null item brief no longer means the entire review service is missing.
- Extend baby responses only with compatible domain-scoped data; never reuse PC corpus as baby evidence. Run `tests/test_review_trace.py tests/test_stage5_review_line.py tests/test_review_summary_api.py` alongside the existing PC202→done and baby HTTP checks. Whole-app checks require resolving the current lists.py merge conflict first.

## EXECUTION

Implement this task, not a plan-only response. Read [CONTRACTS.md](CONTRACTS.md) first. Repository root is `/home/ubuntu/skn_final` in the authoring environment; resolve paths from the actual checkout. Ignore `개발 역할 분담`. This is a continuation work order; inspect and reuse existing upstream/stash implementations, then implement missing acceptance behavior. Verify dependency reports against current code before proceeding.

## READ FIRST

- `src/routers/session.py`
- `src/services/recommendation_service.py`
- `src/repo/engine_repo.py`
- `src/repo/plan_repo.py`
- `src/pipeline.py`
- `frontend/js/core.js`
- `frontend/js/pages/results.js`
- `frontend/js/pages/logs.js`
- `src/routers/dev.py`

## EDIT SURFACE

- `src/routers/session.py`
- `src/services/recommendation_service.py`
- `src/repo/engine_repo.py`
- `src/repo/plan_repo.py`
- `src/pipeline.py`
- `src/schemas.py`
- `frontend/js/pages/results.js, conditions.js, logs.js`
- `frontend/js/core.js`
- `src/services/feedback_service.py (shared producer helper, new)`
- `tests/test_baby_recommendation_http.py (new)`
- `tests/e2e/baby_recommendation.spec.* (new; choose installed browser runner)`

Shared-file changes follow CONTRACTS dependency protocol. Do not overwrite unrelated code; preserve PC regression behavior.

## OBJECTIVE

Complete actual guest HTTP→DB catalog→per-item verification→optimizer→stored result→frontend path. /dev/run, PC scenarios and MINI_CORPUS do not satisfy this task.

## API / INTERNAL CONTRACT

```python
start_recommendation(conn, revision_id, *, strategy="default") -> RecommendAcceptedOut
execute_recommendation(revision_id, run_id) -> None
get_stored_result(conn, revision_id) -> RecommendResultOut-compatible dict
get_owned_result(list_id, principal) -> RecommendResultOut  # optional wrapper, not second pipeline
get_alternatives(list_id, item_id, principal) -> {"items": list[Alternative]}
update_item(list_id, item_id, changes, principal) -> RecommendResult
swap_candidate(list_id, item_id, candidate_id, principal) -> RecommendResult
```

HTTP endpoints:

| Route | Payload / result |
|---|---|
| POST /session/{id}/recommend | {} or {strategy:alternative}; 202 RecommendAcceptedOut; GET returns terminal RecommendResultOut |
| GET /session/{id}/result | 200 stored latest applicable result; 404 before first run |
| PATCH /session/{id}/items/{item_id} | selected?:bool, qty?:1..99, timing?:now/soon/later |
| GET .../items/{item_id}/alternatives | items with candidate_id, current, product, price, price_delta, review? |
| POST .../items/{item_id}/swap | {candidate_id} |
| POST /session/{id}/result-message | {text}, 1..300 chars; {reply,result} |

Result-message handles a documented limited rule set (e.g. cheaper candidate in named slot); ambiguous/unsupported instructions request clarification without mutation. No new LLM dependency.

## TRANSACTION / EXECUTION ORDER

1. Load owned active draft from P1. Reject incomplete inputs 422 before creating run. Obtain stable conditions/domain/lock snapshot; create running run with unique input hash and engine versions. Guard duplicate concurrent run: partial unique constraint or row-lock check; return409 run_in_progress.
2. Resolve P2 requirements, persist them with real requirement IDs in the current revision, then query candidates; persist candidate IDs tied to real requirements/options/observations so P3 refs can link to real rows. Reject foreign-scope IDs even when they exist.
3. Commit started run and return202 after scheduling real background task; inside it perform P3 verification with real run_id and exact corpus. No external embedding inside a long plan transaction. Persist checks/refs with P0 JSON validation. A critical dependency outage may fail whole run; choose explicit policy: unrecoverable DB/embedder failure marks failed and returns stable error; ordinary no_evidence remains pending candidate.
4. P4 ranks/optimizes permitted candidates. Persist item rows and terminal explanation/status consistently (reason text implies ready). Build deterministic explanation from checked facts/excerpts; no forever-pending text when returning done. Infeasible computed result is done with feasible=false/missing_requirements; differs from system failure.
5. In final short transaction lock revision and compare initial lock_version. If changed, commit stale run and do not overwrite current plan. Return409 conflict (or mapped conflict result with consistent API contract). Do not raise inside a transaction that rolls back the stale marker. On exception persist failed in separate valid transaction.
6. GET only loads stored result/JSON refs; do not rerun recommendation, search or embedding. Evidence permission resolution may read current state and redact unavailable text. Map actual stored rule states, not hard-coded unknown/partial. Preserve item_ids on reload.
7. Edits validate ownership, item in current revision, alternative candidate in same requirement/run, current price identity and eligibility. Recalculate using P4, increment lock_version and persist atomic change. Never accept client price, total, evidence or safety verdict. Counter stale expected version with409; avoid lost updates.
8. Alternative strategy chooses a different eligible combination where possible; return explicit no_alternative explanation when none. Do not rotate to an unsafe candidate just to differ.
9. Implement shared append-only event helper for shown/replaced/removed. Idempotency key ties event to run/item/version/action; GET/poll must not duplicate recommendation_shown. P7 uses the same helper for confirmed. P8 consumes and tests these events; do not postpone emission until P8.
10. Wire actual frontend results/items/total/log/empty/infeasible/errors; stop polling terminal states, show retry on failed, explain critical unknown. Preserve same-origin serving. Browser smoke must use real API, not route.fulfill fake JSON.

## ACCEPTANCE

- RH01 actual HTTP guest flow accepts202, then polls stored done result with nonempty synthetic candidates with source notice, checked per-item eligibility and total; evidence locator matches manual; DB run→retrieval→evidence→JSON refs trace exists.
- RH02 result reload has same run/item IDs; monkeypatch embed/search to raise if called on GET and prove no new search. Revocation removes excerpt after reload.
- RH03 incomplete request makes no run; guest B cannot recommend/read/edit guest A list; forged candidate rejected.
- RH04 change condition during delayed embedding → stale committed, current result untouched; concurrent recommend→one active run. Failed embedder→persist failed, no fake no_evidence.
- RH05 swap/quantity/timing/selected edits recompute budget; over-budget/infeasible visible and remains unconfirmable. Alternative returns different eligible item or explicit no-alternative.
- RH06 DB reason/explanation checks pass; no permanent pending terminal output. Events emitted once, GET generates none.
- RH07 browser: create→conditions→recommend→see evidence→swap→reload; collect screenshot and network assertions. Existing PC smoke remains passing.

## VERIFY

```bash
uv run python -m pytest -q tests/test_baby_recommendation_http.py
uv run python -m pytest -q
uv run uvicorn src.api:app --host 127.0.0.1 --port 8000
```

Provide a new deterministic E2E command in package/script config (document the exact command and dependency installation). Seed through P1/P2 and RAG CLI before browser test; do not use frontend mock records. Record HTTP requests/responses with redacted cookies and SQL trace, plus UI screenshot artifact. Missing browser runtime is an explicit unverified RH07, not completion.

## EXIT

All acceptance cases below must have real observed results. Write the completion report specified in CONTRACTS. Update the parent status document only for behavior actually verified. If a dependency or external gate remains unmet, report partial/blocked with its exact failing check; do not replace it with a fixed successful response.
