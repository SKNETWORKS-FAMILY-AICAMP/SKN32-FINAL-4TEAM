---
task_id: "P9"
status: "conditional"
entry_gate: "O1_ready_after_dependencies; O2-O5_explicit_activation"
depends_on: ["P0", "P3", "P5", "P7"]
contract_version: 2
report_path: "docs/agent-tasks/baby/reports/P9.md"
---

# P9 — 운영 검증·자료 처리 확장·RAG 전환 게이트

## CURRENT BASELINE / SYNC DELTA (2026-09-13)

Read [integration audit](reports/sync-2026-09-13.md); this delta overrides obsolete baseline assumptions below.

- Current architecture uses pgvector per latest progress report/code. O4 separate vector DB (not selected) is NOT selected and not a prerequisite; only a new explicit change decision activates it.
- db/setup_all.py now exists; readiness must check applied0010 staging vs completed reduction and fields populated after seed. /health200 and60 tables do not prove target schema ready.
- Current HTTP emulator verification used max_size1/prepare_threshold=None; full SQL run had transport error. O1 must distinguish emulator test results from real PostgreSQL pool/concurrency/worker restart readiness.
- Current async worker is in-process BackgroundTasks; inspect persisted failed/stale/running handling and restarts in O1/O5, preserve latest routes and schema.

## COMMIT DELTA — `30af559..d96ccd2` (2026-09-13)

- O1 readiness now includes application import without lists.py conflict markers, new list_service SQL compatibility on reduced DB, and both0010 migrations applied by full filename with review metadata columns/indexes preserved.
- Record whether the optional ignored PC risk artifact exists, its control_scope/version and unavailable reason. Test missing/malformed/wrong-scope fallback and installed-valid input separately using small fixtures; do not assert a fixed PC recommendation total across artifact states.
- Add review regression tests listed in P8 and list lifecycle HTTP checks from P7 to the affected validation matrix. Prior133-test review precedes this commit delta and is not current verification.

## EXECUTION

Implement this task, not a plan-only response. Read [CONTRACTS.md](CONTRACTS.md) first. Repository root is `/home/ubuntu/skn_final` in the authoring environment; resolve paths from the actual checkout. Ignore `개발 역할 분담`. This is a continuation work order; inspect and reuse existing upstream/stash implementations, then implement missing acceptance behavior. Verify dependency reports against current code before proceeding.

## READ FIRST

- `db_schema_reduction.md`
- `docs/rag_implementation.md`
- `src/rag/embedding.py`
- `src/rag/ingestion.py`
- `src/repo/rag_repo.py`
- `scripts/rag_manual.py`
- `src/workers/ingestion_worker.py`
- `docker-compose.yml`
- `src/config.py`

## EDIT SURFACE

- `docs/agent-tasks/baby/operating-decisions.md (new)`
- `scripts/check_baby_readiness.py (new)`
- `tests/test_baby_readiness.py (new)`
- `docs/agent-tasks/baby/reports/P9.md (new)`
- `remaining runtime/storage/deployment files only for activated subtask below`

Shared-file changes follow CONTRACTS dependency protocol. Do not overwrite unrelated code; preserve PC regression behavior.

## OBJECTIVE / ACTIVATION

P9 in the parent document is not a blanket authorization for a new cloud architecture. Deliver current-path readiness/evaluation tooling now; activate external/provider/upload/deployment changes only for explicitly selected scope. Do not choose a vector database or remove rag tables because this work order exists. Ignore role assignments; the latest pgvector direction is the active baseline; a new vector-store change requires an explicit decision.

Track each subtask as complete/partial/not_selected/blocked with evidence. Overall report separates “readiness tooling complete” from “operational validation complete”. All gates are explicit facts, never waiting by elapsed time.

| Subtask | Activation input | Independent deliverable |
|---|---|---|
| O1 current pgvector readiness | P0/P3/P5/P7 integrated | runnable checks and local deployment/evaluation runbook |
| O2 real document/Bedrock evaluation | authorized scoped documents, evaluation criteria, AWS region/profile access | dataset validator and evaluation harness; actual model run requires inputs |
| O3 PDF/OCR/object store/async ingestion | explicit upload scope, file limit/types/storage backend/runtime | design contract and failure tests specification; implement only chosen path |
| O4 separate vector DB (not selected) | explicit architectural agreement + selected provider + access/retention rules | compatibility interface/contract tests may be designed without removing current path |
| O5 deployment/monitoring | selected hosting target, environments, credentials and publish authorization | build/readiness/runbook; publishing uses supplied scope |

## O1 IMPLEMENT NOW

1. Write operating-decisions.md with selected scope, evidence of decisions and missing inputs; do not invent credentials/targets. Default provider pgvector; price notifications excluded.
2. Build read-only readiness CLI checking DB connection, actual migration version, baby domain/config hash, candidate coverage by need area, pricing/unit validity, exact manual mapping, embedding profile/provider consistency, required API existence and terminal statuses. Separate liveness/readiness/quality; a 200 /health is insufficient.
3. Output JSON `{status,checks:[{id,status,reason,observed}],provider,corpus,versions}` and nonzero exit for required failure. Do not output DSN secrets. Health CLI must not mutate catalog, send messages, charge cloud calls or run recommendation unless explicit evaluation mode selected.
4. Create runbook for local same-origin API and disposable seeded integration test. Existing compose only DB; if O5 local container build is selected add API Dockerfile/compose service with correct project entrypoint, migration step, readiness and graceful shutdown; do not import unrelated Odoo stack.
5. Rerun actual user path and synthetic 21-query evaluation, record latency sample methodology, failures and limits. No new “safety score”. Provide bounded load procedure for later selected environment, not claim throughput without measurement.

## O2 IF ACTIVATED

- Manifest each authorized real manual: exact product/variant/market/language, source rights, hash, version, review status and coverage. Split evaluation questions from indexed corpus; include missing instruction, wrong option, conflicting version, boundary values and withdrawn source.
- Extend evaluation CLI to report retrieval/citation correctness, no-evidence correctness, unsupported instruction rate, latency and provider errors. Retain exact question/citation snapshots and model profile/hash. Acceptance threshold must be selected and written before evaluating, not retrofitted to output.
- Use actual BedrockEmbedder with explicit model/region and separate compatible profile/index. No automatic fallback to local-test. Report actual model run distinctly from mocked request contract test. Missing credentials→blocked model evaluation, independent tests still delivered.

## O3 IF ACTIVATED

1. Authenticated/admin ingestion endpoint validates file type by content, size, hash and ownership; object store object keys scoped and immutable. Quarantine until inspection; no pending/failed file appears published.
2. Parser adapter handles PDF text and explicit OCR path; preserve page/bbox or char locators, fail unsupported scans instead of inventing content. Original never replaced by extracted text.
3. Queue state pending→processing→ready|failed; idempotency (file hash+parser/model version), bounded retries, failure reason, no fake ready. Preserve material current version only after full parse/embed validation; prior published version unaffected by failed attempt.
4. Test duplicate delivery, corrupted/oversized file, OCR failure, object missing, embed failure, revocation during indexing, restart/retry. CLI sync path remains usable.

## O4 IF ACTIVATED

1. Define store adapter parity for publish/search/resolve/revoke/profile/logging, including exact filters, keyword+vector hybrid, stable external run/hit IDs and source hash/locator.
2. Store chunks/vectors/embedding profiles/ingest+retrieval logs in selected vector store or explicitly supported metadata layer. Keep adopted evidence and product facts in RDB. Verify provider actually supports required history and metadata; otherwise decision must address gap, not silently drop audit logs.
3. Stage export/import with counts/hashes, shadow-read old/new corpus, contract/quality comparison, idempotent retry and rollback routing. Never mix embeddings of different profiles. Maintain product scope at search and citation boundary.
4. Resolve RDB evidence to external material/version IDs, recheck current permission; propagate revoke before returning excerpt even if index stale. Handle partial writes as retriable error with no false success.
5. Only after parity/evaluation gates pass and decision is recorded remove rag schema through separate forward migration; preserve trace evidence needed by historical reports. Update tests/environment commands explicitly. Do not claim 29 tables while old path remains active.

## O5 IF ACTIVATED

Build reproducible container/artifact, migrations before app readiness, secret injection, restricted dev route exposure, structured run/error IDs, redacted logs. Test restart/graceful pool closure, missing config, unavailable DB and readiness failure. Publish only to explicitly selected environment and record deployment version+URL, no blanket cloud provisioning.

## ACCEPTANCE / VERIFY

- OV01 readiness checks detect missing seed/profile mismatch/unapplied migration; no DSN secret; default CLI is read-only.
- OV02 local valid reduced schema path reports checks accurately; end-to-end and citation tests produce artifacts.
- OV03 O2 actual real-model run or explicit blocked status; never substitute local-test evidence.
- OV04 unselected O3/O4/O5 produce no runtime infrastructure changes; activated subtasks include their failure cases and parity evidence.
- OV05 changing only readiness tool cannot mark complete the full production quality/user safety objective.

```bash
uv run python scripts/check_baby_readiness.py --corpus synthetic --provider local-test --output generated/operations/readiness.json
uv run python -m pytest -q tests/test_baby_readiness.py
```

Create these CLI flags and report schemas. Final report lists O1–O5 individually, exact activation inputs, executed commands and unverified external requirements. Do not stall all independent work because one optional provider decision is missing.

## EXIT

All acceptance cases below must have real observed results. Write the completion report specified in CONTRACTS. Update the parent status document only for behavior actually verified. If a dependency or external gate remains unmet, report partial/blocked with its exact failing check; do not replace it with a fixed successful response.
