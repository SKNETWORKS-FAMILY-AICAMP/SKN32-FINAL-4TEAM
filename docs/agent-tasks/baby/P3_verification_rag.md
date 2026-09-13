---
task_id: "P3"
status: "pending_baby_integration"
entry_gate: "ready_after_dependencies"
depends_on: ["P0", "P2"]
contract_version: 2
report_path: "docs/agent-tasks/baby/reports/P3.md"
---

# P3 — 후보 안전 조건·설명서 검증·근거 연결

## REVIEW FIXES — 2026-09-13

[검토 결함 수정·현재 계약](reports/P1234-fixes-2026-09-13.md)을 우선 적용한다. 월령 exact 보존, 총 필요량/보유량 분리, 미검토 품목 unknown, 편집 검증과 예산 포함 feasible로 변경됐다. 기존 보고서의 정상 통합 결과 중 무해당 판정에 의존한 자동 선택은 현재 결과로 재사용하지 않는다.

## CURRENT BASELINE / SYNC DELTA (2026-09-13)

Read [integration audit](reports/sync-2026-09-13.md); this delta overrides obsolete baseline assumptions below.

- P0 preserves current RAG runtime but reduced assets/source conversion is incomplete. Guard dependency completion; do not assume0010 means fully migrated store.
- Latest verify_build is PC-only heuristic with unknown RAG/review axes; never reuse its94/100 score as baby safety verdict. verify_baby_manual still exists independently.
- Baby helper still hardcodes real corpus and links explanation refs to validation; these remain actual fixes. Candidate refs restored to JSON, validation_target/evidence still old SQL. Inspect src/reduction_contracts.py and latest EngineRepo before defining replacements.
- Map rule severity to actual DB CHECK values or explicitly migrate them; current helper critical may conflict with old enum. JSON UI severity and SQL enum are distinct contracts.
- P1 exact/range/prenatal semantics must reach scope context; query relevant missing safety inputs rather than treating age chip representative as exact.

## EXECUTION

Implement this task, not a plan-only response. Read [CONTRACTS.md](CONTRACTS.md) first. Repository root is `/home/ubuntu/skn_final` in the authoring environment; resolve paths from the actual checkout. Ignore `개발 역할 분담`. This is a continuation work order; inspect and reuse existing upstream/stash implementations, then implement missing acceptance behavior. Verify dependency reports against current code before proceeding.

## READ FIRST

- `src/rag/contracts.py`
- `src/rag/service.py`
- `src/rag/verification.py`
- `src/repo/rag_repo.py`
- `src/engine/stage3c_verify.py`
- `src/engine/stage5_explain.py`
- `src/engine/stage3a_hardfilter.py`
- `src/services/recommendation_service.py`
- `tests/test_rag_postgres.py`

## EDIT SURFACE

- `src/engine/stage3a_hardfilter.py`
- `src/engine/stage3c_verify.py`
- `src/engine/stage5_explain.py`
- `src/services/recommendation_service.py (candidate helper only)`
- `src/rag/verification.py`
- `src/repo/rag_repo.py (business scope behavior)`
- `src/repo/engine_repo.py (JSON persist API)`
- `tests/test_baby_verification.py (new)`

Shared-file changes follow CONTRACTS dependency protocol. Do not overwrite unrelated code; preserve PC regression behavior.

## OBJECTIVE / INPUT

P0 already preserves old RAG on reduced schema. Add actual per-candidate eligibility and separate adopted verification/explanation evidence. Consume P2 candidates/facts and an existing real recommendation_run created by P5 (tests create an actual run row).

```python
verify_baby_candidate(rag_service, candidate, conditions, run_context) -> CandidateCheck
explain_baby_candidate(rag_service, candidate, check, run_context) -> ExplanationWithRefs
persist_candidate_check(conn, run_id, candidate_id, check, explanation) -> None
resolve_public_evidence(conn, refs, principal_scope) -> list[PublicEvidence]
```

No helper starts an unrelated evaluation run; no global MINI_CORPUS on service path. Do not trust client product keys/run IDs: caller validates ownership, helper validates candidate/run/revision relation.

## RULE/POLICY TABLE

| Fact or retrieval state | Expected |
|---|---|
| exact active recall | eligibility fail, selection_allowed false, explicit recall evidence |
| age/weight/sitting violates applicable manual | fail; preserve measured + threshold + scope |
| missing required safety fact, conflicting facts, unreviewed manual | unknown, auto selection/confirmation false |
| documented conditions all met | eligibility pass for those conditions; coverage partial remains partial |
| review summary absent | no review contribution, not an automatic safety failure |
| search error | error_code, coverage error, no safety pass; not no_evidence |
| synthetic corpus | labeled synthetic, never interpreted as real certificate |

## IMPLEMENTATION

1. Define versioned applicability rules using verified product_fact/evidence. Variant-specific fact overrides model-common only when scope is valid; disagreement in equally applicable verified sources yields unknown with conflict details.
2. Hard-filter true fails before rank. For missing/unknown maintain rejected/pending diagnostic candidate; never promote with score threshold. KC lookup respects relevant product class and explicit evidence; “not applicable” must itself be defined by reviewed rule, not absent data. Use only existing curated/test inputs; no legal standard invention.
3. Construct SearchRequest for validation with exact domain/product/variant/market/language/corpus/run_id and only known age_months, weight_kg, independent_sitting. Map normalized conditions explicitly. Corpus derives from trusted catalog, not hard-coded real.
4. Reuse verify_seat boundary tests for stroller seats. Other classes use their own applicable verified constraints; no seat rule for diaper/cup. Distinguish absence of a rule from successful validation.
5. Run explanation purpose separately using explain_manual; mark and persist only refs actually used for each purpose. Current helper links explanation hits to validation: replace it. Validate JSON refs with P0 contract and link target/run before write.
6. Preserve current publication/file inspection/permissions, material version/hash and applicability filters. Recheck at citation return and again via P5 result reads. Evidence JSON is a reference, not authority to reveal old text.
7. Call embedding outside long DB transaction: obtain immutable search context, perform embedding, short SQL transaction to search+record and revalidate current publication. On mid-query SQL failure preserve error run record using safe transaction boundary; avoid connection reuse in failed state.
8. Return typed verdicts and reason codes; no seeded 80-point score, no inferred complete safety. Expose rule inventory for P4 and P7 eligibility checks.

## ACCEPTANCE

- VE01 real SQL + local-test synthetic manual: months=8, weight=8.5, sitting=true → documented seat constraints pass, partial coverage, exact citation.
- VE02 age below threshold, weight beyond limit, sitting=false independently fail; missing sitting and unreviewed manual unknown.
- VE03 recall fixture excluded even if cheap/high review; missing certificate pending, never auto selected.
- VE04 wrong variant/market/corpus cannot produce evidence; test two products with similar text.
- VE05 verification refs differ from explanation refs when queries use different sections; inspect JSON and retrieval context flags.
- VE06 revoke/permission change between query and citation hides text; evidence trace retained.
- VE07 embedder failure and SQL failure distinct from no_evidence; no fallback provider.
- VE08 malformed/orphan/cross-run JSON refs rejected before persistence.

## VERIFY

```bash
uv run python -m pytest -q tests/test_baby_verification.py tests/test_rag.py tests/test_rag_postgres.py
uv run python scripts/rag_manual.py evaluate --provider local-test --new-test-run --report generated/rag/baby_verification_evaluation.json
```

Test helper creates DB domain/plan/revision/run/candidate, not a dummy run ID. Report stored candidate evidence_refs and validation issues plus trace IDs. Do not require P5 HTTP endpoint for P3 completion; P5 owns end-to-end orchestration.

## EXIT

All acceptance cases below must have real observed results. Write the completion report specified in CONTRACTS. Update the parent status document only for behavior actually verified. If a dependency or external gate remains unmet, report partial/blocked with its exact failing check; do not replace it with a fixed successful response.
