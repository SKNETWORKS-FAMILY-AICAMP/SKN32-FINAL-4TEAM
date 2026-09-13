# Baby schema v1 — P0 v4 (scope/JSON enforcement complete)

Execution policy: `fresh_database_no_legacy_data_migration` (see [P0 work order](P0_schema_contracts.md)). This
supersedes the prior v1/v2 staging reports below the divider — those describe the intermediate
0010/0011 staging migrations, which are still applied (forward-only) but are no longer the final
schema. `db/migrations/0012_schema_reduction_destructive.sql` completes the reduction: obsolete
structures are dropped, replacement columns are made `NOT NULL`/validated, and 0011's `NOT VALID`
constraints are validated. `db/migrations/0013_schema_reduction_scope_constraints.sql` (v4) closes
the last two SR gaps the v3 report left open: the domain snapshot now always carries the rules of
the category that was actually chosen (SR07), and the v1 JSON contracts, revision scope and
evidence run scope are enforced by the database rather than only by convention (SR08).

## What 0013 adds (v4)

| Gate | Enforcement |
|---|---|
| SR07 category binding | `PlanRepo.bind_domain(revision_id, code)`, called by `session_service.choose_category`, re-points `plan_revision.domain_id`/`domain_snapshot` at the **chosen** category's published domain. Before v4 the revision kept whatever `create_session` happened to pick (`ORDER BY updated_at DESC`), so a baby session snapshotted computer's rules — or the RAG evaluation fixture's empty definition and all-zero hash. `create_session` now restricts its placeholder pick to codes that have a `config/categories/*.yaml` file, deterministically. |
| SR07 snapshot content | `plan_revision_domain_snapshot_v1_check` / `recommendation_run_domain_snapshot_v1_check` (`app.domain_snapshot_v1_valid`) reject an empty `definition`, an empty/all-zero `content_hash`, or a non-object `attribute_schema`. `domain_published_definition_check` stops an `active` domain from existing without a real definition. |
| SR08 snapshot immutability | `freeze_domain_snapshot` triggers. `engine.recommendation_run.domain_snapshot` is immutable outright; `planning.plan_revision.domain_snapshot` may change only while the revision is `draft` **and** no run references it — i.e. exactly the category-choice window. |
| SR08 ref item contract | `recommendation_candidate_evidence_refs_items_check` (`app.evidence_refs_v1_valid`) requires every element of `refs` to carry non-empty `evidence_id`, `claim_key`, `material_id`, `material_version`, `file_sha256` and an object `locator`, and rejects duplicate `(evidence_id, claim_key)` pairs. `validation_result_issues_items_check` applies the same item rules to `issues[].evidence_refs` and additionally requires `schema_version=1`, non-empty `rule_key`/`rule_version`, `status IN (pass,fail,unknown)` and an object `target`. |
| SR08 revision scope | `engine.recommendation_candidate.revision_id` (new, `NOT NULL`, set by the `candidate_revision_from_run` trigger from the run — the application cannot set or change it) plus two composite FKs: `rec_candidate_run_revision_fk → recommendation_run(id, revision_id)` and `rec_candidate_requirement_revision_fk → planning.requirement(id, revision_id)`. A candidate can no longer point at another revision's requirement. |
| SR08 evidence run scope | `candidate_evidence_scope` trigger: every `evidence_id` in `refs` must exist, and a `kind='material'` evidence must come from a `rag.retrieval_run` whose `recommendation_run_id` is this candidate's run. Structurally invalid refs are left to the CHECK so the error names the real violation. |
| SR08 seed publication | `db/seed.upsert_domain` raises `PublishedDomainDemotion` when asked to move an already-published domain to `draft`/`disabled` or to publish an empty definition. Both category domains are now seeded `active` — that row is the published condition-conversation rule set the runtime copies. Baby's unfinished recommendation engine (`status: stub` in `baby.yaml`) stays a separate gate and remains 501 until P5. |
| Evidence metadata | `EngineRepo.link_candidate_evidence`/`link_validation_evidence` now resolve `material_id`, `material_version`, `file_sha256` and `locator` from `evidence.evidence` → `rag.retrieval_hit` → `rag.document_chunk` → `rag.ingestion_job` and de-duplicate on `(evidence_id, claim_key)`. Previously they wrote `{evidence_id, claim_key}` only and appended blindly. |
| RAG evaluation fixture | `scripts/rag_manual.create_test_run` creates `rag-evaluation-baby` as `status='disabled'` with a real definition/hash and real snapshots, so it satisfies the snapshot contract and can never be picked as a runtime category. |

## Verified result (real disposable PostgreSQL/pgvector, not a mock)

- `uv run python db/setup_all.py` against an empty disposable DB applies `0000`–`0013`, then seeds
  domain rows and the 51-part computer catalog. A second run is a no-op on migrations and does not
  duplicate seed identities (idempotent).
- Table count: **35** (12→8 schemas: `notification`, `dataset`, `shared` fully removed;
  `config`=1, `identity`=3, `catalog`=7, `planning`=5, `assets`=2, `rag`=6 retained per contract,
  `community`=2, `evidence`=5, `engine`=4).
- `uv run python -m pytest -q` (SQL tests enabled, `DATABASE_URL`/`RAG_TEST_DATABASE_URL` pointed at
  the disposable DB): **100 passed, 3 subtests passed, 0 skipped, 0 failed** (71 before v4 + 29 new
  behavioral cases in `tests/test_schema_reduction_db.py`).
- `uv run python scripts/rag_manual.py evaluate --provider local-test --new-test-run` on the reduced
  schema: **21/21** synthetic manual cases pass (`generated/rag/reduced_schema_evaluation_v4.json`).
- Real HTTP walk (uvicorn against the disposable DB): guest `POST /session` → `POST .../category`
  (computer) → `POST .../answer` (purpose) → `POST .../message` (budget) → `POST .../answer`
  (priority) → `POST .../recommend` (202 `{run_id,status:running}`, real `BackgroundTasks`) →
  `GET .../result` → `status:"done"`, **8 items**, `totals.selected_price=1,493,000`.
  Row inspection on that run: bound domain `computer`, `domain_snapshot->>'content_hash'` equals
  `config.domain.content_hash`, `domain_snapshot->'definition'` equals the domain definition
  (2,923 bytes, not `{}`), run snapshot matches the same hash, **8** requirements with a non-null
  `slot_key` and **0** null, **8** candidates all carrying `revision_id` = the session's revision
  and **0** out of scope. The same walk with `category=baby` binds the **baby** domain and hashes;
  its `POST /recommend` returns **501**, expected until P5/P2 land real rules.
- SR03 fresh-install precondition, proven destructively: applying `0000`–`0011` on a disposable DB,
  inserting a `config.domain` row that bypasses the 0010 backfill (simulating an un-migrated legacy
  install), then running `0012` via `db/migrate.py up` fails atomically with
  `fresh_install_precondition_failed: config.domain has rows not mirrored from domain_version; run
  0010 backfill first` — table count stays at 60 (pre-0012 shape) and `0012` is not recorded in
  `_migrations.schema_migrations`. The chain then applies cleanly again on a fresh disposable DB.

## Physical column mapping (target = current schema after 0012)

| Contract concept | Physical location |
|---|---|
| domain current definition | `config.domain.current_version_no/definition/attribute_schema/content_hash` (single row per domain; `config.domain_version` table removed). Per-revision/run snapshots are frozen at creation time in `planning.plan_revision.domain_snapshot` and `engine.recommendation_run.domain_snapshot` — later domain edits never mutate an existing snapshot. |
| user preferences | `identity.app_user.ui_settings`, `preference_export` (notification-only settings excluded from the live path; `identity.user_preference` removed). |
| unit / dimensional metadata | `catalog.product_variant.unit_code/unit_qty/pack_quantity`, `planning.item.unit_code/unit_qty`, `planning.requirement.unit_code`, `catalog.offer_observation` — plain text/columns, no FK to `shared.unit` (schema `shared` removed; `app.set_updated_at()` replaces `shared.set_updated_at()` for every surviving trigger). |
| category | `catalog.product.category_id` → `catalog.product_category(id)` (real FK; `catalog.product_category_membership` removed). |
| requirement slots | `planning.requirement.slot_key/group_key/position/fulfilled_by_item_id`; `planning.plan_node` removed, `requirement.node_id` dropped. `PlanRepo.ensure_requirement(revision_id, slot_key, match_spec)` manages rows directly by slot key. |
| owned/purchase lines | `planning.item(status IN owned/to_purchase/purchased, qty, unit_code, unit_qty, timing, selected, price_observation, item_spec)`; `planning.owned_item`/`purchase_line`/`fulfillment_allocation` removed. |
| material current version | `assets.product_material(file_object_id, version, source_url, language, retrieved_at, material_status, status, applicability jsonb[], active_ingestion_id, source_name, source_type)` — single current row, no revision history table. `assets.material_revision`/`material_applicability` removed. `rag.ingestion_job.material_id/material_version` link RAG ingestion directly to the material (its own `revision_id` column, which pointed at `material_revision`, is removed). |
| evidence source | `evidence.evidence.source_name/source_type/source_base_url/source_rating_scale` (no `source_id` FK; `evidence.source` removed). `catalog.offer_observation.source_name/source_type` and `evidence.review_summary.source_name/source_type` denormalized the same way. |
| candidate references | `engine.recommendation_candidate.evidence_refs` — `{schema_version:1,refs:[{evidence_id,claim_key,material_id,material_version,file_sha256,locator,retrieval_run_id?}]}`; envelope + per-item keys + `(evidence_id, claim_key)` uniqueness all `CHECK`-validated (0011 + 0013), evidence existence/run scope enforced by trigger. `engine.candidate_evidence` removed; `EngineRepo.link_candidate_evidence` updates the jsonb column directly and de-duplicates. |
| candidate revision scope | `engine.recommendation_candidate.revision_id` — derived from the run by trigger, `NOT NULL`, composite-FK'd to both `recommendation_run(id, revision_id)` and `planning.requirement(id, revision_id)`. |
| validation targets/evidence | `engine.validation_result.issues` — typed array (`ValidationIssue` shape); array type, per-issue `schema_version`/`rule_key`/`rule_version`/`status`/`target` and nested `evidence_refs` item rules all `CHECK`-validated (0011 + 0013). `engine.validation_target`/`validation_evidence` removed; `EngineRepo.link_validation_target`/`link_validation_evidence` update `issues[0].target`/`issues[0].evidence_refs` directly (same call signature as before, minus `purchase_line_id`). |
| community review / PC build | Two target tables: **`community.review`** (`record_type` `review`\|`build`; `domain`, `author_user_id`, `subject_id`, `title`, `body`, `rating`, `axis_scores`, `usage_context`, `attributes` jsonb, `visibility`, `status`, `moderation_status`, `published_at`, `source_plan_revision_id`) and **`community.review_component`** (`review_id`, `slot_key`, `position`, `variant_id`, `quantity`, `component_snapshot`) — folds `pc_build`+`pc_build_version` (as `record_type='build'`, generic attributes jsonb) and `review`+`review_revision` (as `record_type='review'`) into one row each; `pc_build_component` renamed to `review_component`. `evidence.review_subject.build_version_id` and `evidence.review_summary.review_id` now point at `community.review(id)`. |
| notification, dataset | Schemas fully dropped (`DROP SCHEMA notification CASCADE`, `DROP SCHEMA dataset CASCADE`); `src/repo/notification_repo.py`, `src/repo/dataset_repo.py`, `src/services/notification_service.py`, `src/workers/notification_worker.py` deleted (nothing imported them). `catalog.offer_observation`/`review_aggregate` (operational price/review observations) and `engine.feedback_event` are retained. |
| mapping table | `config.schema_reduction_mapping` dropped in `0012` — unused once the fresh-database policy replaced old-row mapping/preservation gates. |

## Supported P0 repository signatures

- `PlanRepo.published_domain(code) -> dict | None` (the only runtime path to published rules),
  `PlanRepo.bind_domain(revision_id, code) -> UUID` (category choice re-binds domain + snapshot;
  raises `Conflict` once the revision is no longer `draft`).
- `db.seed.upsert_domain(cur, code, name, status, definition) -> "created"|"unchanged"|"updated"`,
  raising `db.seed.PublishedDomainDemotion` on a demotion or an empty published definition.
- `src.categories.available_categories() -> list[str]` — codes that have a definition file.
- `PlanRepo.new_revision(plan_id, domain_id, name_snapshot)`, `PlanRepo.ensure_requirement(revision_id, slot_key, match_spec, *, group_key=None, position=0)`, `PlanRepo.load_full(revision_id)`.
- `EngineRepo.start_run(revision_id, domain_id, *, input_snapshot, input_hash, draft_lock_version, engine_versions)` (writes `domain_snapshot` from `config.domain` inside the same statement); `link_candidate_evidence`, `link_validation_target(*, requirement_id=None, candidate_id=None, item_id=None)`, `link_validation_evidence` all update jsonb columns, no join tables.
- `RagRepo.publish_manual/search/record_hits/resolve_evidence/revoke_material/process_job` — same public signatures as before; internals now read/write `assets.product_material` directly instead of joining `material_revision`/`material_applicability`, and `evidence.evidence.source_name/source_type` instead of joining `evidence.source`.
- `ProductRepo.add_observation(offer_id, *, source_name, source_type, observed_at, price, stock_status, quality_status, pricing_terms=None)` — `source_id` positional arg removed.
- HTTP types unchanged: `src.schemas.ConditionState`, `RecommendAcceptedOut`, `RecommendResultOut`, `ItemOut`; JSON storage types `src.reduction_contracts.EvidenceRefs`/`ValidationIssue`.

## Behavioral test coverage for SR01–SR08

`tests/test_schema_reduction.py` keeps the migration-file assertions; `tests/test_schema_reduction_db.py`
(new, 29 cases, gated on `RAG_TEST_DATABASE_URL`) executes the gates against a real database:
SR01 live table enumeration + trigger namespace + no pending migration; SR02 re-seed idempotence,
demotion refusal, published-definition CHECK; SR03 creates its own uuid-named rehearsal database,
applies `0000`–`0011`, plants an un-backfilled legacy row, and asserts `0012` fails with
`fresh_install_precondition_failed` leaving the table count and migration ledger untouched (then
drops only that database); SR07 per-category binding over the real service path, run snapshot match,
non-category domains unreachable, `slot_key` contract; SR08 malformed/duplicate refs and issues,
cross-revision requirement, derived `revision_id`, snapshot survival across a rule change, empty
snapshot rejection, full evidence metadata + dedup on real ingested evidence, cross-run evidence and
unknown evidence rejection.

## Known remaining gaps (explicitly not claimed complete)

- Baby recommendation pipeline itself (rule application, catalog rows) is P2/P5 scope; `run_from_scenario`/`start_recommendation` still raise `NotImplementedError` for `category != "computer"`.
- `community.review`/`review_component` and `src/repo/review_repo.py` are structurally migrated but the review-authoring/aggregation business logic remains `NotImplementedError` (P8 scope) — this task only proves the schema merge is safe and the stubs compile against it.
- `src/repo/material_repo.py` (`MaterialRepo`, `SourceRepo`, `EvidenceRepo`) stays unused `NotImplementedError` scaffolding; nothing imports it, so it is dead code carried forward, not a live SQL path.

---

## Historical (pre-destructive) staging record — superseded by the section above

`0010_schema_reduction_v1.sql` / `0011_schema_reduction_completion.sql` were forward-only staging
migrations that added replacement columns and backfilled them while the legacy tables (created by
`0001_tables.sql`) were still present and readable. That staged/dual-write state is what the
2026-09-13 v1/v2 reports below describe. `0012_schema_reduction_destructive.sql` (this task) is what
actually drops the legacy structures once the fresh-database policy removed the old-row
preservation/mapping gate that previously blocked it. Do not read the paragraphs below as the
current schema — see the physical mapping table above instead.

`0010_schema_reduction_v1.sql` is a forward-only staging migration. RAG remains PostgreSQL/pgvector (six RAG tables), per the controlling contract.

Migration guards reject multiple category memberships and multi-item fulfilment before any destructive operation. A reviewed mapping record belonged in `config.schema_reduction_mapping`, which is now removed — the fresh-database policy replaced that gate.

## Current limitations (as of the destructive migration)

See [sync audit](reports/sync-2026-09-13.md) for the pre-0012 history. As of v4: actual table count is 35 (not 58, not 60); `notification`/`dataset`/`shared` schemas and every table listed in `P0_schema_contracts.md`'s removal table are gone; both seeded domains are `active` with a real definition and hash; PC `requirement.slot_key` values are populated by real writes (verified via the HTTP walk above), not left null; and the revision/run domain snapshot is now proven to match the chosen category's published rules rather than an arbitrary active domain.

## 0014 item reference integrity (2026-09-13)

planning.item now references plan_revision and product_variant. Composite FKs bind (offer_id, variant_id) to catalog.offer and (offer_observation_id, offer_id) to catalog.offer_observation; dependent IDs require their parent IDs. requirement.(fulfilled_by_item_id, revision_id) references item.(id, revision_id), preventing missing/cross-revision fulfillment and parent-key changes that break existing references. All constraints validate existing rows; no silent deletion. See [fix report](reports/P0-fixes-2026-09-13.md).
