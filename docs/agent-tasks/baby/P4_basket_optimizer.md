---
task_id: "P4"
status: "develop_alignment_required"
entry_gate: "ready_after_dependencies"
depends_on: ["P0", "P2", "P3"]
contract_version: 3
report_path: "docs/agent-tasks/baby/reports/P4.md"
---

# P4 — 필수품·예산·구매 시점 최적화

## ACTIVE DB CONTRACT — develop `da79839` / v3 (2026-09-13)

이 절과 [develop 전환 계약](DEVELOP_DB_TRANSITION.md), [목표 스키마](schema-v1.md)가 현재 실행 지시다. 이 문서 아래 기존 지시 중 충돌하는 DB 매핑·pgvector 유지·완전 축소 SR 승인 조건은 폐기한다. DB와 무관한 업무 규칙·API·수용 사례는 유지한다. 과거 보고서의 통과 결과는 당시 코드의 증거이며 develop 호환 완료를 뜻하지 않는다. 현재 작업 트리는 `rag`이므로 develop SQL이 이미 병합되어 있다고 가정하지 않는다. `개발 역할 분담`은 적용하지 않는다.

### P4 DELTA — 계산 로직과 저장 DTO 분리

- **상태/재사용:** 필요량·예산·구매 시점 최적화는 재사용한다. item DB 식별자에 기대는 보유량 계산과 결과 DTO만 변경한다. P2 v3 저장/재조회와 P3의 검증 DTO를 입력으로 사용한다.
- **EDIT:** `src/engine/stage4_optimize.py`, `src/dto.py`, `tests/test_baby_optimizer.py`, `tests/test_baby_db_pipeline.py`, 보유량/편집 결함 회귀.
- **IMPLEMENT:** 보유 충족은 fulfilled_by_item_id의 존재가 아니라 검증된 fulfilled_qty로 계산한다. owned 표시 행 ID는 전환 계약의 파생 ID이며 DB 물품 FK가 아니다. 후보 편집 qty는 develop의 구매 팩 수(정수1~99), 필요량은 qty*unit_qty로 환산한다. 총2/보유1은 한 개만 충족한다. candidate check의 requirement_id 일치와 unit_code를 검증하고, 누락·unknown·fail은 선택/확정을 허용하지 않는다.
- **IMPLEMENT:** 순수 계산이 planning.item에 접근하지 않게 한다. status=owned는 화면/계산용이며 purchase_line을 생성하지 않는다. now/soon/later와 예산 포함 feasible 규칙은 유지한다. HTTP item_id 매핑과 영속 편집은 P5 책임이다.
- **ACCEPTANCE D4:** P2 DB 왕복 DTO로 총2/보유1→구매1; 보유만으로 필수 전체 충족 오판 금지; 후보 교체·단위/수량 오류 거부; 미설정 검색의 unknown 후보 미선택; qty=99 허용/100 거부. 변경되지 않은 순수 예산 테스트 결과는 기존 보고서 참조, 변경한 adapter/보유 경로만 추가 검증한다.
- **HANDOFF:** v3 DTO 입출력과 D4 결과를 `reports/P4.md`에 추가한다.

## PREVIOUS WORK ORDER — non-conflicting business rules only

이하의 날짜별 상태·구 DB 구현 실적은 과거 기록이다. 현재 상태는 위 절과 manifest를 사용한다. 아래 지시에서 완전 축소 SQL 실행, pgvector 보존, planning.item 복원, domain_version/plan_node/purchase_line 삭제, 근거 객체 저장, shared/notification 스키마 삭제를 요구하는 부분은 실행하지 않는다.

## REVIEW FIXES — 2026-09-13

[검토 결함 수정·현재 계약](reports/P1234-fixes-2026-09-13.md)을 우선 적용한다. 월령 exact 보존, 총 필요량/보유량 분리, 미검토 품목 unknown, 편집 검증과 예산 포함 feasible로 변경됐다. 기존 보고서의 정상 통합 결과 중 무해당 판정에 의존한 자동 선택은 현재 결과로 재사용하지 않는다.

## CURRENT BASELINE / SYNC DELTA (2026-09-13)

Read [integration audit](reports/sync-2026-09-13.md); this delta overrides obsolete baseline assumptions below.

- New upstream PC runtime must remain intact. Baby optimizer remains unimplemented beyond existing supplied-list budget helper; reuse restored src.dto baby classes but finish quantity/ID/value validation.
- Current get_stored_result uses candidate ID as item ID, qty1/now and absent price0. These are PC presentation shortcuts; P4 decision + P5 typed items must replace them for baby without regressing PC.
- Target total semantics follow CONTRACTS; current PC budget_share divides selected total, so any changed semantics require explicit field/UI adaptation, not silent global behavior change. Exact safety checks require P3, not PC verification score.

## COMMIT DELTA — `30af559..d96ccd2` (2026-09-13)

- PC `stage3b_rank._review_axis` is implemented: unknown0.5, observed0.75, threshold-exceeding0.25, with REVIEW_OBS flags. Preserve this PC regression; baby still requires its own reviewed analysis and domain-specific controls under this work order.
- Do not apply PC `REVIEW_RISK_CONTROL_SCOPE=Computer Components|Data Storage` or its 2× threshold to baby. Keep missing baby analysis unavailable with no fabricated benefit; P8 must provide a versioned baby-specific input before use.
- Reuse observation/provenance handling where compatible, and verify PC tests `tests/test_rank_review_axis.py tests/test_risk_store_states.py` plus baby no-analysis behavior. PC scoring implementation does not complete P4.

## EXECUTION

Implement this task, not a plan-only response. Read [CONTRACTS.md](CONTRACTS.md) first. Repository root is `/home/ubuntu/skn_final` in the authoring environment; resolve paths from the actual checkout. Ignore `개발 역할 분담`. This is a continuation work order; inspect and reuse existing upstream/stash implementations, then implement missing acceptance behavior. Verify dependency reports against current code before proceeding.

## READ FIRST

- `src/pipeline.py`
- `src/engine/stage3b_rank.py`
- `src/engine/stage4_optimize.py`
- `src/dto.py`
- `tests/test_baby_db_pipeline.py`
- `config/baby_requirement_rules.yaml (P2 output)`

## EDIT SURFACE

- `src/engine/stage3b_rank.py`
- `src/engine/stage4_optimize.py`
- `src/pipeline.py (baby computation boundary)`
- `src/dto.py`
- `tests/test_baby_optimizer.py (new)`
- `tests/test_baby_db_pipeline.py`

Shared-file changes follow CONTRACTS dependency protocol. Do not overwrite unrelated code; preserve PC regression behavior.

## OBJECTIVE / CONTRACT

Pure deterministic budget computation from P2 requirements+candidates and P3 CandidateCheck; no DB lookup, HTTP call or RAG search inside optimizer. P5 handles persistence.

```python
rank_baby_candidates(requirements, candidates, checks, profile) -> RankedCandidates
optimize_baby(requirements, ranked, owned_items, budget_max) -> BasketDecision
recalculate_basket(items, requirements, budget_max, checks) -> BasketDecision
```

Do not reuse PC fixed review=0.5, fixed contributions or seeded safety score. P8 is NOT prerequisite: absent review remains absent; inject typed null and compute remaining configured weights without fabricating review facts.

## ALGORITHM

1. Validate integer KRW price, positive integer purchase qty, unit conversion, stable identities and allowed checks. Mandatory unknown/fail candidates cannot be auto-selected. Track exclusions separately.
2. Fulfill owned quantities first by exact canonical slot+unit; split remaining requirement group as P2 specifies. A physical owned quantity is allocated at most once.
3. Score only valid comparable values. Persist score method version/breakdown and deterministic tie break (lower total price then product_key/variant_key). A profile file documents normalized weights; no undocumented preferred brand.
4. Enumerate one viable candidate/quantity choice per unfulfilled mandatory-now requirement using branch-and-bound for initial catalog. Lower bound of remaining cheapest feasible mandatory choices prunes over budget. Objective is lexicographic: all mandatory-now fulfilled; max configured utility; deterministic price/key tie break. Candidate top-N pruning must be reported as bounded-search approximation, not global optimum.
5. If no mandatory feasible basket, return feasible=false, missing_requirements with required quantity, cheapest feasible subtotal and budget shortfall if computable. No automatic deferral of mandatory-now items. Unknown minimum cost means unknown shortfall, not zero.
6. Add optional-now only within remaining budget. Keep soon/later proposals outside current charge and report separate totals. Explicit timing change of mandatory-now to later yields unmet requirement and blocks confirmation even if budget fits.
7. recalculate handles selection/qty/status/timing edits and swaps identically. Never trust client-submitted price, unit_qty, review or check. P5 supplies authoritative candidate values.
8. Snapshot all inputs needed to reproduce algorithm: profile version, normalized requirements, observations, checks and selected quantities. Keep old run_baby_db_pipeline helper as adapter or retire with consumers/tests migrated; tests must verify real new behavior rather than keep only old greedy example.

## ACCEPTANCE FIXTURES (KRW values intentionally small)

- OP01 budget100: mandatory A options 60/40 and B only60; naive first choice 60+60 fails, optimizer selects40+60 and fulfills both.
- OP02 cheapest mandatory totals110 with budget100 → infeasible, shortfall10, no item silently removed or moved later.
- OP03 owned stroller80 plus to_purchase bottle20 → charged20; purchased items likewise excluded.
- OP04 diaper price10000 per pack, qty2, pack40 → total20000 and80 pieces, not800000.
- OP05 cheap recalled candidate rejected, unknown required safety candidate not selected; missing review candidate still eligible when safety verified.
- OP06 reorder inputs gives same selection; optional item cannot displace mandatory; soon/later do not consume now budget.
- OP07 qty edit/swap recomputes total, over_budget and unmet requirements; negative/missing price or zero qty rejected.
- OP08 owned2 + purchase2 fills required4 once; unit mismatch cannot count fulfillment.

## VERIFY

```bash
uv run python -m pytest -q tests/test_baby_optimizer.py tests/test_baby_db_pipeline.py tests/test_pipeline_smoke.py
```

Add small brute-force oracle over tiny generated cases to verify branch-and-bound equivalence where claiming exact search. Report search bound/time for fixture size, not fabricated number of combinations. Output canonical decision fixture for P5.

## EXIT

All acceptance cases below must have real observed results. Write the completion report specified in CONTRACTS. Update the parent status document only for behavior actually verified. If a dependency or external gate remains unmet, report partial/blocked with its exact failing check; do not replace it with a fixed successful response.
