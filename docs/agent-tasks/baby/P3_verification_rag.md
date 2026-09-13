---
task_id: "P3"
status: "develop_alignment_required"
entry_gate: "ready_after_dependencies"
depends_on: ["P0", "P2"]
contract_version: 3
report_path: "docs/agent-tasks/baby/reports/P3.md"
---

# P3 — 후보 안전 조건·설명서 검증·근거 연결

## ACTIVE DB CONTRACT — develop `da79839` / v3 (2026-09-13)

이 절과 [develop 전환 계약](DEVELOP_DB_TRANSITION.md), [목표 스키마](schema-v1.md)가 현재 실행 지시다. 이 문서 아래 기존 지시 중 충돌하는 DB 매핑·pgvector 유지·완전 축소 SR 승인 조건은 폐기한다. DB와 무관한 업무 규칙·API·수용 사례는 유지한다. 과거 보고서의 통과 결과는 당시 코드의 증거이며 develop 호환 완료를 뜻하지 않는다. 현재 작업 트리는 `rag`이므로 develop SQL이 이미 병합되어 있다고 가정하지 않는다. `개발 역할 분담`은 적용하지 않는다.

### P3 DELTA — RAG 제거 후 검증·근거 연결

- **상태:** 가장 큰 전환 대상. 과거 pgvector 21/21 및 P3 DB 통과는 새 설계의 검색 완료 증거가 아니다. P0/P2의 저장 매핑을 먼저 사용한다.
- **EDIT:** `src/rag/{service,verification,ingestion,evidence_search,contracts}.py`, `src/repo/{rag,material,engine}_repo.py`, `src/engine/stage3c_verify.py`, 검색 설정/CLI 및 `tests/test_baby_verification.py`, `tests/test_rag*.py`.
- **IMPLEMENT:** `rag.*` SQL 실행을 서비스·적재·평가 진입점에서 제거한다. 신규 검색 provider Protocol은 `publish(document)->external_document_id`, `search(query,filters)->hits`, `resolve(hit_id)->hit|None`, `revoke(document_id)`를 제공한다. hit에는 provider/외부 hit ID/material_revision_id/product_id/variant_id/file_sha256/locator/text/corpus가 필요하다. 청크·벡터·검색 로그는 외부 provider 책임이고 PostgreSQL에는 선택된 결론과 출처만 쓴다. backend 미설정 시 명시적 unavailable을 반환하고 필수 검증은 unknown/selection_allowed=false로 마친다. 고정 성공값이나 기존 pgvector로의 암묵적 fallback은 금지한다.
- **IMPLEMENT:** 실제 backend 제품·접속 설정은 현재 코드에서 확인되지 않았다. 우선 provider 경계·미설정 경로·메타데이터 검증을 구현할 수 있다. 실제 외부 backend 선택/설정과 publish→search→resolve→revoke 통합 증거가 확보되기 전 D3-02와 P3 전체 완료는 blocked로 남긴다. 인터페이스 목 테스트로 그 게이트를 대신하지 않는다.
- **IMPLEMENT:** material은 product_material→material_revision→file_object 및 material_applicability로 확인한다. 삭제된 rag FK가 남긴 `active_ingestion_id`를 게시 여부로 신뢰하지 않는다. source_id를 통해 evidence.source를 조회한다. 조회 때 원문 revision의 published/권한/상품·옵션 적용/해시/철회 여부를 다시 검사한다.
- **IMPLEMENT:** evidence.kind=material 행의 retrieval_hit_id는 develop에 남은 UUID 컬럼과 CHECK를 준수한다. 공급자의 임의 문자열 ID를 UUID로 강제 변환하지 않는다. 앱이 발행한 UUID를 이 필드에 쓰고 facts에 provider/external_hit_id/material_revision_id/file_sha256을 보존한다. 실제 검색 hit가 없으면 material 근거를 생성하지 않는다. 외부 URL 사실은 external_fact의 별도 CHECK를 따른다. citation_snapshot에는 원문 위치와 당시 출처를 저장한다.
- **IMPLEMENT:** candidate.evidence_refs에는 v3 배열을, validation_result.issues에는 target(candidate_id,requirement_id) 포함 배열을 쓴다. JSON 저장 전에 run→revision→requirement 및 제품 범위를 재검사한다. 검증과 설명 근거를 분리하고 미확인 인증·설명서 규칙은 unknown으로 유지한다.
- **ACCEPTANCE D3-01:** rag 스키마가 없는 DB에서도 앱/PC/유아 오류 처리 정상; provider 미설정/타임아웃은 unknown 및 선택 금지; JSON 배열 저장/재조회, 다른 run/상품 근거 거부; 철회 후 원문 비공개.
- **ACCEPTANCE D3-02:** 실제 외부 backend에 자료 게시·검색·원문 위치 일치·제품/옵션 범위 제한·철회·재시작 후 복원까지 확인. synthetic 설명서 실적과 실제 상품의 검증 범위를 구분한다.
- **HANDOFF:** `reports/P3.md`에 D3-01과 D3-02를 별도로 기록한다. P5는 미설정 상태를 표시할 수 있지만 이것을 검증 가능한 추천 완료로 보고하지 않는다.

## PREVIOUS WORK ORDER — non-conflicting business rules only

이하의 날짜별 상태·구 DB 구현 실적은 과거 기록이다. 현재 상태는 위 절과 manifest를 사용한다. 아래 지시에서 완전 축소 SQL 실행, pgvector 보존, planning.item 복원, domain_version/plan_node/purchase_line 삭제, 근거 객체 저장, shared/notification 스키마 삭제를 요구하는 부분은 실행하지 않는다.

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
