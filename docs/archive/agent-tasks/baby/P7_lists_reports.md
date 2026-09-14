---
task_id: "P7"
status: "develop_alignment_required"
entry_gate: "ready_after_dependencies"
depends_on: ["P5", "P6"]
contract_version: 3
report_path: "docs/agent-tasks/baby/reports/P7.md"
---

# P7 — 목록·확정 스냅샷·리포트·판매처 이동

## ACTIVE DB CONTRACT — develop `da79839` / v3 (2026-09-13)

이 절과 [develop 전환 계약](DEVELOP_DB_TRANSITION.md), [목표 스키마](schema-v1.md)가 현재 실행 지시다. 이 문서 아래 기존 지시 중 충돌하는 DB 매핑·pgvector 유지·완전 축소 SR 승인 조건은 폐기한다. DB와 무관한 업무 규칙·API·수용 사례는 유지한다. 과거 보고서의 통과 결과는 당시 코드의 증거이며 develop 호환 완료를 뜻하지 않는다. 현재 작업 트리는 `rag`이므로 develop SQL이 이미 병합되어 있다고 가정하지 않는다. `개발 역할 분담`은 적용하지 않는다.

### P7 DELTA — 확정·리포트를 purchase_line으로 전환

- **상태:** planning.item 기반 완료 기록은 과거 설계 실적. P5의 후보 편집/재계산과 P6 소유권 계약을 먼저 확인한다.
- **EDIT:** `src/services/list_service.py`, `src/repo/plan_repo.py`, 목록/리포트 API 및 테스트. develop notification.price_watch 참조를 깨뜨리지 않는다. 유아 알림 발송 신규 기능은 별도 범위다.
- **IMPLEMENT:** 확정은 revision 잠금+If-Match→현재 run 검사→P3 안전 상태/P4 필수량·예산 재검사→purchase_line 쓰기→revision confirmed 갱신을 한 트랜잭션으로 수행한다. 보유 행은 구매 행에서 제외한다. 선택 구매 후보의 qty를 pack_count에, qty*검증된 단가를 line_amount에 저장한다. 기존 add_purchase_line의 pack_count=1 고정값을 유아 수량을 받는 호환 인자로 확장한다.
- **IMPLEMENT:** snapshot은 schema-v1의 purchase snapshot 필드를 기록한다. 관측값이 해당 offer와 variant에 속하는지 검사한다. soon/later 구매도 snapshot에 timing을 남기고 now 합계와 별도 집계한다. 재확정은 기존 snapshot을 반환하며 중복 INSERT하지 않는다. purchased는 이번 과업의 별도 DB 상태가 아니며 완료 구매 이력 기능으로 확대하지 않는다.
- **IMPLEMENT:** 리포트는 purchase_line.snapshot과 확정 당시 조건/보유/합계 snapshot만 사용한다. 현재 상품명·가격·후보를 JOIN해 과거 내용을 덮어쓰지 않는다. 보유·부족량을 포함한 확정 보고 snapshot은 전환 계약의 run.input_snapshot.baby_confirmation에 동일 트랜잭션으로 고정한다.
- **ACCEPTANCE D7:** 수량2의 line_amount와 pack_count 일치; now/soon/later 별도합; 보유품 무청구; 누락 가격·unknown 필수 안전·다른 offer 관측값 거부; 재확정 중복0; 상품/조건 변경 후 기존 리포트 동일; 교차 사용자 거부; 기존 PC 목록·리포트·price_watch 경로 유지.
- **HANDOFF:** 실제 purchase_line 및 확정 snapshot/리포트와 D7 결과를 `reports/P7.md`에 추가한다.

## PREVIOUS WORK ORDER — non-conflicting business rules only

이하의 날짜별 상태·구 DB 구현 실적은 과거 기록이다. 현재 상태는 위 절과 manifest를 사용한다. 아래 지시에서 완전 축소 SQL 실행, pgvector 보존, planning.item 복원, domain_version/plan_node/purchase_line 삭제, 근거 객체 저장, shared/notification 스키마 삭제를 요구하는 부분은 실행하지 않는다.

## RESOLVED REVIEW FINDINGS — 2026-09-13

목록 서비스의 축소 DB 전환과 물품 참조 제약 누락은 수정됐다. `0014_item_reference_integrity.sql`을 적용하고 `tests/test_p0_list_item_integrity.py`로 검증한다. 최신 결과는 [수정 보고서](reports/P0-fixes-2026-09-13.md) 참조. 아래 COMMIT DELTA의 구 표 SQL·라우터 충돌 안내는 과거 문제이며 이 해결 기록이 우선한다. P7 전체 사업 규칙 완료를 의미하지 않는다.

## CURRENT BASELINE / SYNC DELTA (2026-09-13)

Read [integration audit](reports/sync-2026-09-13.md); this delta overrides obsolete baseline assumptions below.

- Superseded by d96ccd2: list/rename/delete/confirm/report route and service implementations now exist, but reduced-DB integration is outstanding. Stash already removes alert route and report alert behavior; preserve these removals, do not re-add due to old frontend document.
- Current PC result item IDs are candidate IDs, not stable planning.item; P5 must establish actual editable item identity before immutable confirmation snapshots.
- Keep latest202 recommendation and current ItemOut shape. P0 plan_node/item migration is incomplete, so confirm cannot assume full reduced schema from0010 alone.

## COMMIT DELTA — `30af559..d96ccd2` (2026-09-13)

- Baseline is now partial upstream implementation: GET /lists, PATCH/DELETE /lists/{id}, POST confirm and GET report delegate to list_service. Reuse owner checks, soft deletion, row locking, login gate, selected-item/PC-budget checks and snapshot-writing intent; do not rebuild route scaffolding.
- Blocking integration: current router has merge markers; service uses removed domain_version/plan_node/purchase_line tables. Coordinate reduced-SQL changes with P0 before claiming HTTP availability. Keep alert removal.
- Remaining business work: replace quantity1/now assumptions with P4 selected items and quantities; add If-Match, mandatory/safety/evidence checks, correct baby now-budget calculation, append-only confirmation/new-draft semantics and idempotent feedback. Report currently reads current revision and current plan name; LR04 must prove historical snapshot preservation after rename/edit. Derive stage from successful usable result, not existence of any run.
- VERIFY after integration: guest create→GET lists→rename→delete; logged-in owner recommend→confirm→report; cross-owner404, guest confirm401, repeat confirm and concurrent-edit cases. Use real reduced PostgreSQL and existing LR01–LR07; implementation presence alone is not a pass.

## EXECUTION

Implement this task, not a plan-only response. Read [CONTRACTS.md](CONTRACTS.md) first. Repository root is `/home/ubuntu/skn_final` in the authoring environment; resolve paths from the actual checkout. Ignore `개발 역할 분담`. This is a continuation work order; inspect and reuse existing upstream/stash implementations, then implement missing acceptance behavior. Verify dependency reports against current code before proceeding.

## READ FIRST

- `src/routers/lists.py`
- `src/services/list_service.py`
- `src/repo/plan_repo.py`
- `src/schemas.py`
- `frontend/js/pages/confirm.js`
- `frontend/js/pages/report.js`
- `frontend/js/planner-shell.js`
- `frontend/js/core.js`
- `db/migrations/0008_frontend_contract.sql`

## EDIT SURFACE

- `src/routers/lists.py`
- `src/services/list_service.py`
- `src/repo/plan_repo.py`
- `src/schemas.py`
- `frontend/js/pages/confirm.js, report.js`
- `frontend/js/planner-shell.js`
- `src/services/feedback_service.py`
- `tests/test_baby_lists_reports_http.py (new)`
- `tests/e2e/baby_confirm_report.spec.* (new)`

Shared-file changes follow CONTRACTS dependency protocol. Do not overwrite unrelated code; preserve PC regression behavior.

## OBJECTIVE / API

Complete user list lifecycle and immutable confirmation; no checkout, price poll or notification.

| Route | Input / output |
|---|---|
| GET /lists | guest or account owned active plans →{items:[{list_id,name,category,stage,updated_at}]} |
| PATCH /lists/{id} | {name}1..60 →ListSummary |
| DELETE /lists/{id} | soft delete →204 |
| POST /lists/{id}/confirm | name, planned_purchase_at?, target_amount?, memo?≤1000 →Report, logged-in only |
| GET /lists/{id}/report | immutable current confirmed report, logged-in owner only |

Report frontend shape: list_id,name,category,owner_display_name,planned_purchase_at,target_amount,memo,total,confirmed_at,items[{slot,slot_label,product,price,qty,timing,review?,evidence_text}],data_notice. Omit/remove price_watch contract and UI; target_amount is static metadata, not alert subscription. Add confirmed_revision_id and structured evidence/status for traceability.

## IMPLEMENTATION

1. Lists filter active owned plan and usable account; order updated_at desc plus stable id tie break. Compute stage from real category/conditions/current result/confirmed revision, not client page. Rename does not change item identities; deletion sets status/deleted_at and hides all mutation/read routes consistently.
2. Confirm requires If-Match lock_version per CONTRACTS; transaction locks plan+draft and validates owner, active user, current lock/run, nonempty selected purchase rows, feasible mandatory requirements, now budget and all required eligibility. Recheck current evidence availability/critical rules, not just stored pass. Missing data→422 explicit reason. Target amount/date/memo validated; unknown body fields cannot alter product or price.
3. Persist immutable revision/item snapshot with exact variant, quantity, units, now/soon/later, observation ID, price, adopted refs, timestamp, domain/engine versions. Preserve plan_revision; do not update shared mutable item rows. Represent confirmation state distinctly from item status purchased.
4. Confirm retries must not create duplicate snapshots/events for same revision (unique confirmed transition/idempotency handling). If edits resume, create a new draft revision copying items/conditions to new IDs; old confirmed rows remain immutable. Guard two-tab confirm/edit race with locks/version conflict.
5. GET report returns snapshot prices/names/quantities even if catalog price changes. Evidence visibility remains dynamic: snapshot text must be redacted if currently revoked, while event/price history persists. Do not call recommender/embedding on GET.
6. Use server-stored http(s) purchase URLs only; sanitize display and disable missing/unsafe URLs. Frontend opens actual merchant URL; click is not proof of payment, never marks purchased. Label synthetic/no-merchant data.
7. Append plan_confirmed via P5 shared feedback helper after successful transition, idempotent and transactionally consistent. No event on failed confirmation. No private memo copied into analytics payload.
8. Connect confirm→login redirect(return destination)→resume→report; prevent open redirect by allowing only same-app destinations. Align sidebar reload/rename/delete with API outcomes.

## ACCEPTANCE

- LR01 guest can list/rename own plan, cannot confirm/report until login; B cannot access A; deleted plan inaccessible.
- LR02 eligible budget-compliant selection confirms; invalid input, empty/over-budget/unmet safety/infeasible/stale draft fail with no snapshot/event.
- LR03 retry confirmation creates one snapshot and one event. Concurrent edit/confirm yields consistent version or409.
- LR04 change catalog price and new draft quantities afterward: old report unchanged. Mutating old confirmed row through API rejected.
- LR05 revoke manual→report keeps price history but hides old excerpt. GET makes no external search call.
- LR06 missing URL disables link; link click does not set purchased. No alert API/network call.
- LR07 browser guest recommendation→signup/login→confirm→report→reload→new draft edit→old report preserved.

## VERIFY

```bash
uv run python -m pytest -q tests/test_baby_lists_reports_http.py tests/test_baby_recommendation_http.py tests/test_password_auth_http.py
```

Deliver deterministic E2E command and snapshots of confirmed vs current draft DB rows, not only rendered text. Account and data are local test fixtures; no purchase action.

## EXIT

All acceptance cases below must have real observed results. Write the completion report specified in CONTRACTS. Update the parent status document only for behavior actually verified. If a dependency or external gate remains unmet, report partial/blocked with its exact failing check; do not replace it with a fixed successful response.
