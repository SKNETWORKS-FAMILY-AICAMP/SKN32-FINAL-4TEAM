---
task_id: "P0"
status: "partial_rework_required"
entry_gate: "ready_after_dependencies"
depends_on: []
contract_version: 2
report_path: "docs/agent-tasks/baby/reports/P0.md"
---

# P0 — 축소 DB·공통 계약·기존 코드 호환

## RESOLVED REVIEW FINDINGS — 2026-09-13

목록 서비스의 축소 DB 전환과 물품 참조 제약 누락은 수정됐다. `0014_item_reference_integrity.sql`을 적용하고 `tests/test_p0_list_item_integrity.py`로 검증한다. 최신 결과는 [수정 보고서](reports/P0-fixes-2026-09-13.md) 참조. 아래 COMMIT DELTA의 구 표 SQL·라우터 충돌 안내는 과거 문제이며 이 해결 기록이 우선한다. P7 전체 사업 규칙 완료를 의미하지 않는다.

## ACTIVE DIRECTION — FRESH DATABASE (user decision)

- Execution policy: `fresh_database_no_legacy_data_migration`. This supersedes the old data-preservation/mapping gates in prior P0 reports and readiness reviews. HTTP/DTO contract remains v2; this is an acceptance-policy change, not a wire-format change.
- Reuse current code, 0010 and 0011 work. P0 remains partial until the new acceptance cases below pass. No full application rewrite.
- No old-row backfill, ID preservation, conflict mapping tool, historical database export or seeded old-to-new rehearsal is required for this direction. Recreate reproducible synthetic/catalog/RAG data from repository files. New runtime data must still have correct relationships, snapshots and provenance.
- The current instruction changes the work order; it does not itself delete a database. Default execution creates a dedicated empty disposable DB and leaves other databases untouched. Replacing an existing DB is allowed only when that exact target is established as disposable with no data to preserve. Record host/port/database/environment without secrets. If target identity or data disposition is unknown, continue in the isolated DB; do not infer disposability from row counts. Do not use broad volume deletion or delete unrelated databases/files.
- Implementation record: v2 fixed seed current-domain writes and ensure_requirement slot writes; v3 (`0012`) ran the destructive completion and converted every live SQL consumer; **v4 (`0013`) closed the last two gaps listed here** — `new_revision`/category-choice domain_snapshot and published-rule selection consistency (`PlanRepo.bind_domain`, called by `choose_category`; both category domains seeded `active`; RAG evaluation domain `disabled`), and the JSON/scope constraints (per-item `evidence_refs`/`issues` CHECKs, `recommendation_candidate.revision_id` + composite FKs, evidence run-scope and snapshot-immutability triggers). Old SQL dependencies were already removed in v3. Behavioral acceptance for SR01–SR08 is in `tests/test_schema_reduction_db.py`. Preserve current HTTP schemas, baby questions and real PC 202/background execution.

## COMMIT DELTA — `30af559..d96ccd2` (2026-09-13)

- Reopened compatibility scope: `src/services/list_service.py` added by `d96ccd2` queries `config.domain_version`, `planning.plan_node`, `planning.purchase_line`; these are removed by the working-tree reduction. Convert category lookup to the reduced domain contract, slot lookup to requirement.slot_key, and confirmation/report storage to planning.item snapshots. Do not restore removed tables. Business validation remains P7.
- Preserve upstream `0010_review_summary_relation_axis.sql`: nullable evidence.review_summary.author_ref/review_posted_at and two indexes. The runner keys by full filename stem, so two `0010_*` files are distinct; verify sorted fresh application through0013 and repeat setup, and column/index survival. Do not rename/delete applied files or copy their ALTER statements blindly into applied reduction SQL; use a new forward migration if needed.
- `src/routers/lists.py` currently has unresolved merge markers. Integration implementation must preserve upstream routes and the removal of alerts, then verify application import. This documentation update does not resolve source conflicts.
- Add fresh-DB list lifecycle smoke checks to SR06/SR09 and review-summary column checks to SR01/SR03. Earlier P0 test results predate these upstream consumers and cannot establish compatibility.

## EXECUTION

Implement this task, not a plan-only response. Read [CONTRACTS.md](CONTRACTS.md) first. Repository root is `/home/ubuntu/skn_final` in the authoring environment; resolve paths from the actual checkout. Ignore `개발 역할 분담`. This is a continuation work order; inspect and reuse existing upstream/stash implementations, then implement missing acceptance behavior. Verify dependency reports against current code before proceeding.

## READ FIRST

- `db_schema_reduction.md`
- `db/migrations/0000_prereq.sql`
- `db/migrations/0001_tables.sql`
- `db/migrations/0002_unique.sql`
- `db/migrations/0003_foreign_keys.sql`
- `db/migrations/0004_triggers.sql`
- `db/migrations/0005_indexes.sql`
- `db/migrations/0006_rag_active_profile.sql`
- `db/migrations/0007_app_user_password_auth.sql`
- `db/migrations/0008_frontend_contract.sql`
- `db/migrations/0009_frontend_requirement_revision.sql`
- `db/migrations/0010_schema_reduction_v1.sql`
- `db/migrations/0011_schema_reduction_completion.sql`
- `db/migrations/0012_schema_reduction_destructive.sql`
- `db/migrations/0013_schema_reduction_scope_constraints.sql`
- `docs/agent-tasks/baby/reports/P0.md` (v4 is the latest implementation record)
- `docs/agent-tasks/baby/schema-v1.md` (physical column mapping + 0013 enforcement table)
- `src/repo/rag_repo.py`
- `src/repo/plan_repo.py`
- `src/repo/engine_repo.py`
- `src/schemas.py`
- `src/dto.py`
- `frontend/js/core.js`
- `docs/frontend_외부수정요청.md`

## EDIT SURFACE

- `db/migrations/<next>_schema_reduction*.sql (new)`
- `src/repo/*_repo.py (mechanical schema adaptation)`
- `src/services/session_service.py (domain reference only)`
- `src/services/recommendation_service.py (JSON adapter only)`
- `scripts/rag_manual.py`
- `src/schemas.py`
- `src/dto.py`
- `src/reduction_contracts.py`
- `db/seed.py`, `db/seed_catalog.py`, `db/setup_all.py`
- `config/categories/baby.yaml`
- `frontend/js/api.js, core.js, pages/*.js (contract compatibility and alert removal)`
- `tests/test_schema_reduction.py (extend)`, `tests/test_schema_reduction_db.py (SR01-SR08 behavioral)`
- `tests/test_rag_postgres.py`
- `tests/rag_pg/server.mjs`
- `docs/db/table_spec.md`

Shared-file changes follow CONTRACTS dependency protocol. Do not overwrite unrelated code; preserve PC regression behavior.

## OBJECTIVE

Apply confirmed reductions and keep existing independent RAG/PC behavior executable. Complete shared contract v2 for downstream tasks. Do not leave P1/P3 to repair a broken baseline migration. Business recommendation/auth implementations remain downstream.

## IMPLEMENTATION

1. Inventory SQL references with `rg -n 'domain_version|user_preference|shared\.|plan_node|owned_item|purchase_line|fulfillment_allocation|material_revision|material_applicability|evidence.source|candidate_evidence|validation_target|validation_evidence|review_revision|dataset\.|notification\.' src scripts tests db`. Separate historical migration text from live SQL. Inspect actual columns/FKs; do not trust reduction document's “unused code” statements.
2. Use one reproducible bootstrap path: allocate the next unused forward migration after0011, keep0000–0011 checksums unchanged, apply the chain to an EMPTY disposable DB, then remove obsolete structures in the new migration, then run adapted seeds. Old staging backfills see empty tables; no old data conversion work is needed. Do not seed before the final reduced schema exists. Do not maintain a second independent schema definition. Existing populated DB upgrades are outside this work order; document that deployment requires a fresh database and prevent accidental upgrade of a populated legacy DB (explicit fresh-install precondition before applying the chain).
3. Implement the target structures below and adapt every live consumer. Remove obsolete FKs/triggers in a dependency-aware order; replace required functions before dropping their old schema. Inspect dependent objects rather than using unrestricted CASCADE. Remove the now-unused schema_reduction_mapping table. New rows must satisfy the target contract; no legacy compatibility tables retained solely to avoid converting code.

| Removed source | New-write target / required behavior |
|---|---|
| config.domain_version | config.domain current version/definition/attribute_schema/hash; new revision/run snapshots retain the version and rules used. Seed and runtime select the same published rules; later rule changes must not mutate existing snapshots. |
| identity.user_preference | app_user preference fields/defaults; notification-only preferences excluded. No old preference export required. |
| shared.unit | catalog unit_code/unit_qty plus required dimensional metadata; timestamp function in retained namespace with all triggers rebound. |
| product_category_membership | product.category_id, canonical category enforced for new input; invalid/ambiguous new input rejected. |
| plan_node | requirement.slot_key/group_key/position; new callers do not need node IDs. |
| owned_item + purchase_line | planning.item with revision/status/quantity/unit/timing/selection/variant/price and source snapshot; validate FK and revision scope. |
| fulfillment_allocation | requirement.fulfilled_by_item_id; split quantities through group_key without double counting. Mechanical storage support is P0; baby matching/rules remain P2. |
| assets.material_revision/applicability | product_material current file/version/state/permission/applicability; ingestion links material identity/version. Newly created citations preserve their version/hash across later replacements/revocation. |
| evidence.source | evidence source attributes and explicit provenance on catalog observations and other consumers; no deleted source FK. |
| candidate_evidence | candidate.evidence_refs typed object with validated IDs/scope, deduplication and material/version/hash/locator metadata. |
| validation_target/evidence | validation_result.issues typed array preserving targets and evidence on every new write. |
| community PC/review tables | common review domain/attributes/current body/status; document exact two target community tables. Business review APIs remain P8. |
| notification, dataset | removed schemas and runtime consumers; datasets live in files. Retain feedback_event and operational observations. |


4. Freeze field and method contract implementation in schemas/dto; document exact physical column mapping in `docs/agent-tasks/baby/schema-v1.md` (new deliverable). Existing DTOs may adapt internally, public frontend shape must match CONTRACTS. Add structural validation for JSON and run ownership checks to EngineRepo JSON accessors.
5. Adapt RagRepo ingest/search/resolve/revoke and evaluation fixture creation to reduced assets/evidence/config. Keep pgvector profiles, chunk hashes, search logs and active profile isolation. Existing CLI still works on new DB. No loss of product option or applicability filtering.
6. Adapt PlanRepo and EngineRepo SQL including reason_status paired with reason. get_latest_run status/JSON mapping must not hard-code verification states. Mechanical wrappers may stay temporarily but never query deleted tables. Unsupported business methods remain explicitly unsupported until their task.
7. Remove /lists/{id}/alert route, notification UI/calls/worker entry wiring, dataset SQL repo usages; if obsolete module imported, remove import or replace with explicit unsupported entry rather than broken import. Keep operational price observations, review statistics and feedback_event.
8. Extend current frontend-ready ConditionState and RecommendResultOut, mapping of internal status to public status. Implement parsing/serialization tests; no new fake UI fixture returned in production. Supply rule schema / allowed slot codes; P2 supplies actual need rules and catalog rows.

## ACCEPTANCE — replacement gates (not the historical SR02/SR03)

- SR01: empty disposable DB applies0000–0011 plus completion migration and adapted seeds via db/setup_all.py. Enumerate actual tables and deviations from the35-table target (six rag retained); obsolete structures and mapping table absent. Do not remove required functionality to hit a count.
- SR02: repeat bootstrap/seed/migrate on the initialized target; no duplicate seed identities, no reset of runtime data, no pending migration. This replaces old-to-new data-preservation rehearsal.
- SR03: fresh-install precondition rejects a populated legacy target before destructive DDL. Record the exact disposable target and recreated fixture sources. Invalid/ambiguous NEW category or item input fails atomically. No legacy mapping implementation is required.
- SR04: existing21 RAG query cases plus revocation/version/permission/SQL failure tests pass on the new schema. Reingest checked-in synthetic documents; keep behavior assertions, do not weaken them to suit table removal.
- SR05: no live SQL references deleted structures, including seeds/fixtures/CLI; timestamps still update. Historical migrations and historical reports may name deleted tables.
- SR06: current ConditionState/RecommendResultOut round trips and frontend field usage pass. No alert route or UI request; no competing baby-only shared DTO.
- SR07: fresh setup → real guest create/category/message/answer/reload → PC POST recommend202 → GET done, existing fixture8 items. Inspect NEW rows: domain definition/hash, nonempty revision snapshot, requirement slot_key and new-schema references. Empty-table NULL counts alone are insufficient. Baby recommendation501 remains expected until P5.
- SR08: real SQL tests reject malformed JSON (including missing keys), missing/cross-revision references and invalid quantities; enforce evidence/run scope and deduplication. Snapshot remains unchanged after current domain rules change. Seed cannot promote an unpublished version over a published one. Apply/validate constraints to the final DB, not merely NOT VALID declarations.
- SR09: current HTTP/JSON serialization and actual repository writes agree; all required metadata is populated. No removed DTO imports. P1/P2 can consume documented physical columns and repository signatures without reviving old tables.

## VERIFY / OUTPUT

```bash

# DATABASE_URL must identify the dedicated disposable DB, never an implicit default.
uv run python db/setup_all.py
uv run python db/migrate.py dry-run
uv run python -m pytest -q tests/test_schema_reduction.py tests/test_recommendation_schemas.py
uv run python -m pytest -q tests/test_rag.py tests/test_rag_postgres.py tests/test_pipeline_smoke.py tests/test_frontend_static_serving.py
uv run python scripts/rag_manual.py ingest --provider local-test
uv run python scripts/rag_manual.py evaluate --provider local-test --new-test-run --report generated/rag/reduced_schema_evaluation.json
```

Use real isolated PostgreSQL/pgvector for SQL and HTTP acceptance. Add behavioral tests for the replacement SR01–SR09; source-string assertions alone are insufficient. No old-schema fixture conversion or mapping report is required. Execute setup a second time and verify idempotence. Run the full test suite with SQL tests enabled; report no skips as completion evidence. Publish schema-v1.md, actual migration filenames, seed/ingest commands and repository signatures for P1–P8. Record target identity, fixture hashes, counts and HTTP/DB assertions without credentials.

P1/P2 gate: after replacement SR01–SR09 pass, both may proceed using the same completed schema/contracts. Before then, only independent pure logic/data preparation is ready. Legacy data migration is no longer a blocker; live SQL conversion, snapshots, constraints and fresh-install regression still are.

## EXIT

All replacement acceptance cases above must have real observed results. Write the completion report specified in CONTRACTS. Update the parent status document only for behavior actually verified. If a dependency or external gate remains unmet, report partial/blocked with its exact failing check; do not replace it with a fixed successful response.
