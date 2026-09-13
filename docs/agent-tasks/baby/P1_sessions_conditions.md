---
task_id: "P1"
status: "partial_upstream"
entry_gate: "ready_after_dependencies"
depends_on: ["P0"]
contract_version: 2
report_path: "docs/agent-tasks/baby/reports/P1.md"
---

# P1 — DB 접속·게스트 세션·조건 수집

## REVIEW FIXES — 2026-09-13

[검토 결함 수정·현재 계약](reports/P1234-fixes-2026-09-13.md)을 우선 적용한다. 월령 exact 보존, 총 필요량/보유량 분리, 미검토 품목 unknown, 편집 검증과 예산 포함 feasible로 변경됐다. 기존 보고서의 정상 통합 결과 중 무해당 판정에 의존한 자동 선택은 현재 결과로 재사용하지 않는다.

## CURRENT BASELINE / SYNC DELTA (2026-09-13)

Read [integration audit](reports/sync-2026-09-13.md); this delta overrides obsolete baseline assumptions below.

- Status: **partial upstream implementation**, not blank service. Pool/lifespan, truefit_guest, GET/message/answer/reset and slot_rules exist. Reuse them and existing db/seed.py rather than creating parallel pool/seed modules.
- Current POST session is200 (keep for compatibility; do not recreate201 solely from old spec). Real baby field collection and reload pass. Recreating a second session rotates cookie and makes first list404: fix guest identity reuse.
- age_stage is display-only derived from age_months. Grouped-age chips are representative values and prenatal0 collides with true newborn0: normalize range/exact/prenatal and ask exact age when needed. Do not overwrite latest questions with empty stub.
- Add allowed field/type/options/none validation, category/reset semantics, persistent draft invalidation/lock_version and row scope; current handlers do not satisfy these acceptance cases. Fix broad “없어요” extraction so missing belongings does not assert healthy skin.
- Align domain binding with reduced config; current create picks any active domain and baby seed is draft. Preserve working PC condition path and extend existing interfaces.

## COMMIT DELTA — `30af559..d96ccd2` (2026-09-13)

- Preserve `bce91b8` frontend behavior: choosing another category creates a new list, retaining the original conversation; when cached category is unknown, fetch it first. Server-side same-list category changes still need existing reset/ownership checks.
- Reuse `tfResetMark/tfSetResetMark/tfClearResetMark` in core.js: restart hides earlier messages using a per-list localStorage marker and retains server history; list deletion clears the marker. Do not describe this as deleting chat history.
- Add browser verification: baby→computer creates distinct list IDs; both remain accessible with the same guest cookie; restart→answer→reload keeps restart question/history display stable, and delete clears only that list marker. Source change is present; current list-router conflict prevents claiming whole-app verification.

## EXECUTION

Implement this task, not a plan-only response. Read [CONTRACTS.md](CONTRACTS.md) first. Repository root is `/home/ubuntu/skn_final` in the authoring environment; resolve paths from the actual checkout. Ignore `개발 역할 분담`. This is a continuation work order; inspect and reuse existing upstream/stash implementations, then implement missing acceptance behavior. Verify dependency reports against current code before proceeding.

## READ FIRST

- `src/db/__init__.py`
- `src/auth/deps.py`
- `src/services/session_service.py`
- `src/repo/plan_repo.py`
- `src/repo/user_repo.py`
- `src/routers/session.py`
- `config/categories/baby.yaml`
- `frontend/js/pages/conditions.js`
- `frontend/js/pages/category.js`
- `frontend/js/core.js`

## EDIT SURFACE

- `src/db/__init__.py`
- `src/api.py`
- `src/auth/deps.py`
- `src/services/session_service.py`
- `src/repo/plan_repo.py`
- `src/repo/user_repo.py`
- `src/routers/session.py`
- `config/categories/baby.yaml`
- `src/schemas.py`
- `pyproject.toml, uv.lock`
- `db/seed.py (existing; extend)`
- `tests/test_baby_session_http.py (new)`

Shared-file changes follow CONTRACTS dependency protocol. Do not overwrite unrelated code; preserve PC regression behavior.

## OBJECTIVE / DEPENDENCY OUTPUT

Consume P0 schema-v1, ConditionState and cookies. Make guest create→category→message/answer→save→reload work with actual SQL. Do not wait for account auth P6; guest implementation must later accept the same Principal extended by P6.

## API CONTRACT

| Method path | Request | Success |
|---|---|---|
| POST /session | {} | 200 {list_id}, guest cookie (reuse valid guest identity for multiple lists) |
| GET /session/{list_id} | — | 200 ConditionState, category nullable |
| POST .../category | {category: baby, mode?: born/prenatal} | state, initial question |
| POST .../message | {text}, 1..500 chars | appended user/assistant messages + extracted state |
| POST .../answer | {question_id,selected:[string]} | state |
| PATCH .../slot | {field,value}, null clears | state |
| POST .../reset | {} | empty conditions/messages, keep selected category |

Expose common `load_owned_draft(conn,list_id,principal)` and `normalize_baby_conditions(state)->NormalizedConditions` for P5/P7. Methods do not create their own unrelated DB transactions.

## IMPLEMENTATION

1. Reuse latest psycopg pool dependency/lockfile and FastAPI lifespan. Complete lifecycle/rollback/concurrency tests; lazy test lifecycle allowed. `get_conn` yields a connection, commits on success, rolls back on exception, returns connection to pool. Dependency startup failure is explicit; /health alone remains liveness, not readiness.
2. Seed current baby domain from checked-in YAML by deterministic hash/upsert. No arbitrary latest domain choice. Category-null session may have a draft with nullable domain or controlled initial binding from P0 contract; do not use fake evaluation domain.
3. Store guest token hash; generate token once per valid guest, persist cookie; returning guest can create multiple lists and see all own lists. Invalid/missing token cannot access an existing list. Invalid authenticated token must not silently downgrade to guest.
4. Make question_sets and required_inputs match public fields. Parse known Korean patterns: “8개월”, “예산 30만원”, “300,000원”, known needs, explicit none. Ambiguous numbers ask a question; no generic extraction of first numeral as age/budget. Unknown response leaves missing. Preserve explicit user answers versus suggested defaults.
5. Validate allowed fields, strict bool, nonnegative integer months, positive money/weight, mode/date consistency, mutually exclusive none. All mandatory values are required even if hidden in text. Ask optional safety conditions only after relevant need identified; no false can_recommend for category=null.
6. Persist messages and condition supersession atomically. Category change clears incompatible fields/results; patch/reset increments lock_version and stales old result. ConditionState derived from persisted current revision, not process globals. Support no-op message as a stored note without fabricating condition changes.
7. Check ownership before revealing current state, including every new route. Scope all row reads to plan and revision. Use concurrency-safe revision/condition locking and retry/conflict handling; one active condition per key.
8. Connect frontend without token localStorage. Keep P5 recommend route untouched except reusable precondition validation helper. If recommendation invoked before P5 exists, explicit not implemented remains; do not call that full service completion.

## ACCEPTANCE MATRIX

- SS01 no cookie→POST session→Set-Cookie; category-null can_recommend=false; fresh second request sees same saved state.
- SS02 POST message “8개월, 예산 30만원” yields months=8 and budget=300000; fill remaining chips incl none and can_recommend=true. Clear budget→false, preserve old condition history.
- SS03 “몰라요”, negative budget, fractional months, unknown field, none+other, invalid date → missing/422 as appropriate, no invalid condition insert.
- SS04 guest B cannot GET/PATCH/reset guest A list; stale/forged cookie no access; malformed UUID returns controlled validation.
- SS05 pool rollback removes partial message/condition updates; two concurrent changes leave valid lock/history, no duplicate active condition.
- SS06 prenatal due date and born age roundtrip independently; changing mode clears incompatible conditions.

## VERIFY / HANDOFF

```bash
uv run python db/seed.py
uv run python -m pytest -q tests/test_baby_session_http.py
uv run uvicorn src.api:app --host 127.0.0.1 --port 8000
curl -c /tmp/truefit-guest.txt -X POST http://127.0.0.1:8000/session
# Use returned real UUID and the cookie jar for /category, /message, GET.
```

New tests use real database plus HTTP client, two distinct clients. If httpx/TestClient needed add dependency; avoid replacing get_conn with a dict store. Capture response state, SQL condition/history rows, and ownership failures.

## EXIT

All acceptance cases below must have real observed results. Write the completion report specified in CONTRACTS. Update the parent status document only for behavior actually verified. If a dependency or external gate remains unmet, report partial/blocked with its exact failing check; do not replace it with a fixed successful response.
