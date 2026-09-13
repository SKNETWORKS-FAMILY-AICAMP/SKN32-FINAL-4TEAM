---
task_id: "P5"
status: "partial_pc_only"
entry_gate: "ready_after_dependencies"
depends_on: ["P1", "P2", "P3", "P4"]
contract_version: 2
report_path: "docs/agent-tasks/baby/reports/P5.md"
---

# P5 — 추천 실행·저장·결과·후보 편집 API

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
