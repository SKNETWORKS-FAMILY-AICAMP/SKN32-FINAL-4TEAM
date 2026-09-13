# Baby implementation contracts — v3 (develop DB alignment)

## Active authority — 2026-09-13

현재 기준은 **develop `da79839`의 DB 설계**다. [DEVELOP_DB_TRANSITION.md](DEVELOP_DB_TRANSITION.md)와 [schema-v1.md](schema-v1.md), 각 Pn의 ACTIVE DB CONTRACT가 이 문서 아래 과거 계약의 충돌 부분을 대체한다. 코드 구현과 DB 적용은 아직 완료하지 않았다. 이번 v3는 내부 저장 계약 변경이며 기존 HTTP URL/응답의 호환 가능한 업무 규칙은 유지한다.

| 기존 지시 중 폐기 대상 | v3 지시 |
|---|---|
| pgvector/rag 유지, 별도 검색 전환 미선택 | develop 최종 DB에 rag 없음; 외부 provider 경계 및 실제 연결 게이트는 P3 |
| domain 통합/domain_id·domain_snapshot | domain_version 유지, revision/run.domain_version_id 및 입력 스냅샷 |
| requirement.slot_key 물리 컬럼 | plan_node.template_key를 DTO.slot_key로 매핑 |
| planning.item와 fulfilled_by_item_id 저장/FK | 조건 출처와 match_spec의 보유량; 후보 편집; purchase_line 확정 |
| evidence_refs wrapper 객체 저장 | 개별 ref의 검증 규칙을 보존한 JSON 배열 저장 |
| source/material/review 통합 | evidence.source, material_revision/applicability, review_revision 유지 |
| notification/shared 스키마 제거 | price_watch와 shared.set_updated_at() 유지 |
| auth_version 필수 | develop iat 기반 무효화; P6 동일 초/탈퇴 회귀 게이트 |
| 기존 SR01~09/35개 테이블로 P0 승인 | P0-D0-01~03, 목표 관계/필드/행동 검증 |

미변경 업무 계약(정확한 월령, 단위/예산, unknown 선택 금지, 게스트 소유권, 조건 잠금, 비동기202, 자료 철회, 합성 자료 표시)은 아래 정의를 재사용한다. 내부 DTO의 fulfilled_by_item_id, stable item ID, evidence wrapper 및 확정 snapshot 규칙은 전환 계약의 v3로 대체한다. 새로운 에이전트는 ENTRYPOINT에서 전환 계약을 먼저 읽고 과거 실행 명령을 그대로 실행하지 않는다. 과거 RAG 테스트 환경은 새 DB 검증 환경이 아니다. 현재 상태는 manifest, 실제 검증 증거는 날짜별 reports를 따른다.

## Previous contract — unaffected business/API clauses only

이하의 Authority/status, baseline·완료 상태와 DB 환경은 과거 기록이다. 현재 지시와 모순되는 문장은 실행 권한이나 승인 기준으로 사용하지 않는다.

## Authority / status

- These files are executable work specifications, not implementation reports. Read [sync audit](reports/sync-2026-09-13.md) first. Some symbols now exist upstream or in partial P0; inspect and extend them. Proposed missing fields are remaining work, not current API guarantees.
- Source priority: current user instruction > `db_schema_reduction.md` confirmed decisions > current frontend contracts > product/technical planning. Source paths are relative to repository root. Read repository `AGENTS.md` first. Ignore `개발_역할_분담.md`, its assignments and restrictions.
- Current baseline: `d96ccd2` (delta from `30af559`) + existing uncommitted P0–P2 work; lists.py merge conflict remains, Python 3.11, FastAPI, Pydantic v2, psycopg, HTML/JS frontend. Reinspect working tree before editing; do not revert unrelated changes. Resolve dependency revisions using actual code, not baseline assumptions.
- Latest 2026-09-13 progress report and code retain PostgreSQL/pgvector. Old proposal wording about separate vector DB is historical, not an active migration instruction; replacing it requires a new explicit change decision. The other schema reductions are confirmed. Price notifications are excluded and their schema is removed. Research datasets live in files, not dataset SQL tables. Do not remove recommendation feedback logging.
- Also read [upstream progress report](../../작업_진행_보고_2026-09-13.md) and [canonical reduction proposal](../../db/db_schema_reduction_proposal_2026-09-12.md). Read [implementation status](../../유아용품_서비스흐름_구현현황_2026-09-12.md), [DB reduction](../../../db_schema_reduction.md), [frontend contracts](../../frontend_외부수정요청.md). Historical table specs describe input to migration, not the target schema.

## Commit integration requirements — `d96ccd2`

- Latest list service reintroduces legacy-table consumers; P0 handles reduced SQL compatibility and P7 completes confirmation behavior. Preserve implemented routes without restoring removed tables. Current source conflict prevents whole-app verification.
- Review metadata migration uses its full filename as migration identity; preserve nullable author_ref/review_posted_at and indexes. P8 reuses public summary/PC observation implementation; baby analysis and feedback still require completion. P4/P5 preserve PC ranking/explanation regressions without importing PC thresholds into baby.
- Frontend category switching now creates a new list and restart only hides earlier messages; preserve P1 ownership and reset semantics. Commit impact details and verification steps are in affected work orders.

## Active P0 database policy (supersedes historical migration gates)

User selected a fresh DB without legacy data migration. Follow [P0 work order](P0_schema_contracts.md) replacement SR01–SR09. Old reports/reviews remain historical evidence; their old-row mapping, export and preservation gates no longer block completion. Use a dedicated empty disposable DB by default; existing database deletion requires an identified disposable target. Preserve current code/HTTP contracts, convert live SQL and validate new writes, snapshots and fresh setup before P1/P2 integration. This policy does not mark P0 complete or change DTO contract_version2.

## Dependency and editing protocol

1. `manifest.json` dependencies are completion gates, not instructions to create agents. Work on a task only after dependency outputs are present and their acceptance tests pass; independent pure logic can be drafted sooner but is not an integrated completion.
2. P0 resumes from partial 0010/0011 staging on an empty disposable DB and completes reduced SQL, mechanical repository/CLI compatibility and shared types. No full restart; do not overwrite applied0010. The latest db/seed.py, seed_catalog.py, setup_all.py and PC executor are additional migration consumers. It does not implement all downstream business functions. P1 reuses implemented DB lifecycle/guest condition handlers and completes their validation/ownership semantics; P6 extends the same identity boundary for accounts. P3 adds business verification after P0 preserves existing RAG behavior.
3. Downstream tasks consume P0 types. If a missing column/field is required, update the canonical contract, producer, consumers, fixtures and relevant tests in the same change. Never keep a private incompatible DTO.
4. Shared-file edits (schemas.py, dto.py, routers/session.py, config, migrations, dependencies) must integrate the latest file contents. Allocate the next unused migration number; never assume 0010 remains free. No second competing ORM/schema tree.
5. Every task must finish code + meaningful tests + reproduction + report. `TODO`, fixed success payloads, browser fake data and silent mock fallbacks are not completion.

## Canonical service contracts (implementation defaults for P0)

### Scalars and identity

- UUID strings in HTTP; UUID in repositories. ISO dates, UTC ISO timestamps. Integer KRW for public money; DB Decimal must be integral before serialization. Negative/missing price is unavailable, not zero.
- Domain is `baby`; mode `born|prenatal`. Stable product_key and variant_key identify a model and option; database IDs are separate. Corpus `synthetic|real`, market `KR`, language `ko` are explicit metadata.
- Guest cookie `truefit_guest`; auth cookie `truefit_session`. Both HttpOnly, Path=/, SameSite=Lax, Secure on HTTPS. Local HTTP mode must be explicit. Frontend uses credentials=include. HTTP never requires JavaScript to store auth/guest secrets.
- Server Principal contains optional user_id/guest token hash. Every list read/write first checks owner, active plan and revision relation. Authenticated requests must validate account status. Other-owner or absent object: 404. No dummy principal. Check Origin for cookie-authenticated mutations against configured same-origin/allowed origins; preserve existing CLI/test callers with explicit documented no-Origin policy.
- Validation error: `{error:{code,message,field}}`. Missing auth 401; other-owner 404; stale revision 409; bad input 422; stable public dependency error 503. No credential/raw SQL exception in response.

### Conditions target / current compatibility

```json
{"category":"baby","mode":"born","age_stage":{"months":8,"label":"8개월"},"due_date":null,"needs":["수유","외출"],"health_skin":["none"],"owned_items":["유모차"],"budget_max":300000,"weight_kg":8.5,"independent_sitting":true}
```

- Current upstream stores age_months and derives age_stage for display. Preserve the UI shape, normalize internally; chips currently substitute representative ages (1/5/9/18/30) and0 for prenatal. These are not exact safety inputs. P1 must distinguish range/exact/unknown/prenatal and ask exact values for relevant P3 rules before claiming suitability.
- Target base required: category, mode, age_stage.months (born) OR due_date (prenatal), nonempty needs/health_skin/owned_items, positive budget_max. `none` is exclusive, converted to empty internal list but retained as an explicit answered state. Missing and explicitly none differ.
- Months is nonnegative integer. Optional positive finite weight and strict bool sitting are requested only for relevant rules. Do not infer sitting from age, allergies from prose, or safety eligibility from a UI age label. Prenatal has no fabricated infant weight/age.
- Allowed needs: 수유, 이유식·식사, 수면, 외출, 목욕·위생, 기저귀·배변, 의류, 놀이, 안전·건강. Internal slot codes stable, Korean labels separate.
- ConditionState public fields: list_id, category(nullable), mode, messages[{id,role,text}], fields[{key,label,value,display,status,editable}], next_question(nullable), can_recommend, accepts_spec_file=false for baby, revision_id, lock_version. field status confirmed|assumed|missing. next_question `{id,field,text,select:single|multi|free,options:[{value,label}]}`. Return compatible frontend shapes, not raw DB rows.
- PATCH slot null clears condition and invalidates current recommendation. Every material mutation increments draft lock_version. Computation uses immutable normalized snapshot plus domain version/config hash.

### Pipeline boundary models (partial P0 src.dto definitions exist; wiring/validation remain)

```text
BabyRequirement: id, revision_id, slot_key, group_key, required_qty, unit_code,
  mandatory, timing(now|soon|later), constraints, fulfilled_by_item_id?, fulfilled_qty?
BabyCandidate: candidate_id, requirement_id, product_id, variant_id, product_key,
  variant_key, name, slot_key, price:int?, offer_observation_id?, observed_at?,
  stock_status, pack_quantity, unit_code, unit_qty, corpus, market, language,
  facts, review_summary?, score_breakdown
CandidateCheck: candidate_id, requirement_id?, eligibility(pass|fail|unknown),
  verification(partial|unknown|verified), coverage(partial|full|none|error),
  selection_allowed:bool, issues[], explanation_evidence[], error_code?
BasketItem: item_id, requirement_id, group_key, candidate_id?, variant_id?,
  status(owned|to_purchase|purchased), selected, qty, unit_code, unit_qty,
  timing, unit_price?, offer_observation_id?, validation
BasketDecision: items[], totals{selected_price,selected_units,budget_remaining,
  over_budget,soon_price,later_price}, missing_requirements[], feasible, alternatives
```

`selection_allowed` is not product safety certification. fail never allowed. Unknown on mandatory safety rule: retain visible diagnostic candidate, disallow auto selection/confirmation until resolved. Missing review alone does not exclude. Real unverified safety facts cannot be substituted with synthetic ones. Fixture “pass” only means declared synthetic constraints pass.

### Evidence JSON schema v1

```json
{"schema_version":1,"refs":[{"evidence_id":"uuid","claim_key":"manual_applicability","material_id":"uuid","material_version":"v1","file_sha256":"sha256","locator":{"section_code":"S07","line_start":44,"char_start":645,"char_end":941},"retrieval_run_id":"uuid"}]}
```

Store this object in recommendation_candidate.evidence_refs. validation_result.issues is an array of typed objects:

```json
[{"schema_version":1,"rule_key":"baby_seat","rule_version":"v1","target":{"candidate_id":"uuid","requirement_id":"uuid","item_id":null},"status":"unknown","severity":"critical","measured":{"age_months":8},"threshold":{},"reason":"missing_sitting","penalty":null,"evidence_refs":[]}]
```

No fabricated penalty/confidence. P0 writes complete new records; legacy field migration is excluded under the active fresh-DB policy. Target IDs must belong to run/revision and evidence IDs exist with matching product scope. New JSON structure checks in Pydantic and repository validation; JSON storage has no automatic FK for IDs. Verification evidence and explanation evidence remain separate. Persist references, not unchecked live excerpts. Return current allowed excerpts after revalidation; include redacted/unavailable reason when revoked. Source attributes move into evidence.evidence, no evidence.source dependency.

### Public RecommendResultOut (latest canonical HTTP type)

Existing `src.schemas.ConditionState`, `RecommendAcceptedOut`, `RecommendResultOut`, `ItemOut` are canonical. Keep progress=list, conditions_summary=str, computer+ baby compatibility. `src.reduction_contracts` contains restored EvidenceRefs/ValidationIssue and validates structure only. Do not resurrect the stash-only baby-only RecommendResult or removed src.dto.RecommendationResult family. Add missing revision/lock/evidence/status fields compatibly and update producers/tests.

Target extension of frontend D-4-2: list_id, run_id, revision_id, lock_version, status(running|done|failed|conflict), progress, category, conditions_summary, budget_max, items, totals, verification, explanation, reasoning_log, data_notice, error?. Each item has item_id, slot/slot_label, product{product_key,variant_id,name,brand,spec_summary,image_url,purchase_url}, price, price_source, price_observed_at, qty, selected, timing, budget_share, review(nullable), reason, checks, alternatives_count, plus explicit evidence/eligibility/coverage fields. reason/checks/explanation use pending|ready|failed. Terminal output must not leave endless pending. Null purchase URL disables purchase link. Do not invent review count/confidence to fill UI.

- POST recommend preserves latest **202 {run_id,status:running} + actual BackgroundTasks execution**; GET result returns the terminal result. Extend `start_recommendation(conn, revision_id, strategy)` / `execute_recommendation(revision_id, run_id)` / `get_stored_result(conn, revision_id)`; do not add a competing synchronous pipeline. DB statuses running/completed/failed/stale map to running/done/failed/conflict (stale currently maps failed; compatible correction remains work). Persist failure/conflict after rollback, execute immutable start snapshot, recover abandoned runs on process restart; in-process tasks are not a durable queue.
- Mutable item/confirm requests send `If-Match: <lock_version>` from the latest state/result. Reject stale version with409; missing version on revision-mutating API is422. Update the frontend adapter to pass it. A fresh recommend can acquire current version server-side, but publication still compares its start version.
- Candidate IDs belong to a run. item_id is stable during a revision; swapping candidate preserves item_id. New revision gets new mutable rows; preserve grouping keys for presentation.
- Total now = selected to_purchase rows with timing=now, sum(unit_price*qty). owned/purchased excluded. soon/later separately reported. selected_units uses same charged rows; budget_share=charged row total/budget_max. Keep display selection of deferred rows distinct from currently charged rows.
- No optimality or safety percentage without computed evidence. Public completion means computation ended; an infeasible basket must show missing required items and cannot confirm.

## Verification environment

Existing tools: uv, Python3.11, tests/rag_pg/server.mjs, db/migrate.py. Inspect before creating: latest db/seed.py, db/seed_catalog.py, db/setup_all.py and P0 tests/test_schema_reduction.py already exist. New unimplemented names remain deliverables. See sync audit for which behaviors/tests were actually run.

```bash
uv sync --locked
uv run python -m pytest -q
# Terminal A, disposable DB, Node >=20 recommended
npm ci --prefix tests/rag_pg
node tests/rag_pg/server.mjs
# Node18 fallback if CustomEvent unavailable:
# node --input-type=module -e 'globalThis.CustomEvent ??= class CustomEvent extends Event { constructor(type, options = {}) { super(type, options); this.detail = options.detail; } }; await import("./tests/rag_pg/server.mjs")'
# Terminal B
export DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:55432/postgres?sslmode=disable'
export RAG_TEST_DATABASE_URL="$DATABASE_URL"
uv run python db/migrate.py up
uv run python -m pytest -q
```

Never point integration tests at an existing user/production DB. Historical old-schema result was 65 passed + 3 subtests; current merge basic tests42 passed/27 skipped, SQL suite68 passed/1 PGlite transport error (isolated case rerun passed). Do not call this an all-pass new-schema validation; 21/21 single synthetic manual queries. These counts are historical, not future thresholds or new-schema certification. Preserve behavioral cases when adapting fixtures. No database skips or setup errors in final P0 SQL verification. PGlite transport/pool limitations are not production defects: for HTTP emulator rehearsal use test-only single connection/prepare_threshold=None from sync audit, never alter production pool merely to conceal emulator errors. Verify multi-connection behavior with real PostgreSQL. P0 fixes Node18 tool compatibility or pins supported Node in repository.

## Completion report protocol

Write `docs/agent-tasks/baby/reports/Pn.md` and include:

```yaml
task_id: Pn
status: complete | partial | blocked
commit_or_tree: actual value
dependency_revisions: {P0: actual value}
implemented_contract_version: actual value
changed_files: []
tests: [{command: actual, result: actual, passed: 0, failed: 0, skipped: 0}]
reproduction: [actual commands and expected observed output]
artifacts: [repo-relative paths]
remaining: []
```

Include actual response/DB proof, model and corpus where used. Never mark complete on code-only inspection, mocks of the persistence path, removed tests, or unavailable credentials. If external access is missing, implement and test independent parts, record the exact blocked acceptance case; do not claim operational verification.

## Review fixes — 2026-09-13

P2 persistence returns one real requirement UUID per slot with total required_qty and explicit fulfilled_qty, and saves the same DTO under match_spec.baby_requirement for load_persisted_baby_requirements. P4 subtracts only that owned coverage. recalculate.feasible requires valid inputs, mandatory coverage and budget compliance. P3 CandidateCheck includes requirement_id for cross-requirement checks. No reviewed non-stroller manual exemptions are currently available; absent rules mean unknown, not pass. See [fix report](reports/P1234-fixes-2026-09-13.md).
