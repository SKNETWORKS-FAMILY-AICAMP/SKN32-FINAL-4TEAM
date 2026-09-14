---
task_id: "P2"
status: "develop_alignment_required"
entry_gate: "ready_after_dependencies"
depends_on: ["P0"]
contract_version: 3
report_path: "docs/agent-tasks/baby/reports/P2.md"
---

# P2 — 유아 카탈로그·단위·필요 품목 규칙

## ACTIVE DB CONTRACT — develop `da79839` / v3 (2026-09-13)

이 절과 [develop 전환 계약](DEVELOP_DB_TRANSITION.md), [목표 스키마](schema-v1.md)가 현재 실행 지시다. 이 문서 아래 기존 지시 중 충돌하는 DB 매핑·pgvector 유지·완전 축소 SR 승인 조건은 폐기한다. DB와 무관한 업무 규칙·API·수용 사례는 유지한다. 과거 보고서의 통과 결과는 당시 코드의 증거이며 develop 호환 완료를 뜻하지 않는다. 현재 작업 트리는 `rag`이므로 develop SQL이 이미 병합되어 있다고 가정하지 않는다. `개발 역할 분담`은 적용하지 않는다.

### P2 DELTA — 카탈로그·필요량·보유량 저장 전환

- **상태/재사용:** 상품 정규화와 필요 품목 순수 규칙은 재사용. `persist_baby_requirements`와 재조회는 DB 전환 필요. P0의 매핑과 fixture를 사용한다.
- **EDIT:** `src/engine/stage2_requirement.py`, `src/repo/{plan,catalog,product}_repo.py`, 유아 시드/적재 CLI, `src/dto.py`, `tests/test_baby_catalog.py`, `tests/test_baby_requirements.py`, 관련 DB 회귀.
- **IMPLEMENT:** 슬롯마다 `ensure_node(revision_id, template_key=slot_key)` 후 `ensure_requirement(revision_id,node_id,match_spec)`를 호출한다. requirement.quantity/unit_code/required에 총 필요량을 기록하고 DTO.slot_key는 node.template_key에서 복구한다. 중복 슬롯 동시 생성은 revision 잠금으로 직렬화한다.
- **IMPLEMENT:** `planning.item`, `fulfilled_by_item_id` SQL과 `_find_or_create_owned_item`을 제거한다. 보유 출처는 plan_condition UUID로, 보유 충족량은 `match_spec.baby_requirement`의 v3 owned 필드로 저장한다(전환 계약 참조). DTO는 fulfilled_qty를 사용하고 fulfilled_by_item_id를 폐기한다. 같은 슬롯을 보유/구매 조각으로 만들더라도 실제 requirement UUID 하나로 합친다. 조건에서 보유를 제거하면 owned와 fulfilled_qty도 지운다. 다른 revision의 condition UUID는 거부한다.
- **IMPLEMENT:** 상품은 product.category_id에 단일 분류를 쓰고 단위 사전은 코드로 검증한다. 관측값과 설명서 출처는 evidence.source, material_revision/applicability 관계를 사용한다. seed가 shared.unit·통합 domain·통합 material 컬럼을 만들지 않게 한다.
- **ACCEPTANCE D2:** 멱등 적재; 총2개/보유1개→필요 구매1개; 저장·재조회·재실행에서도 같은 requirement 및 결과; 보유 해제→구매2개; 단위 불일치/음수·비유한값/교차 revision 조건 거부. 상품/가격 출처와 synthetic 표식을 유지한다.
- **HANDOFF:** 실제 requirement+node+condition 행과 DTO 왕복, D2 결과를 `reports/P2.md`에 기록한다. 새 스키마에 없는 item FK 테스트는 동일한 교차 소유권·수량 검증 사례로 옮기고 단순 삭제하지 않는다.

## PREVIOUS WORK ORDER — non-conflicting business rules only

이하의 날짜별 상태·구 DB 구현 실적은 과거 기록이다. 현재 상태는 위 절과 manifest를 사용한다. 아래 지시에서 완전 축소 SQL 실행, pgvector 보존, planning.item 복원, domain_version/plan_node/purchase_line 삭제, 근거 객체 저장, shared/notification 스키마 삭제를 요구하는 부분은 실행하지 않는다.

## REVIEW FIXES — 2026-09-13

[검토 결함 수정·현재 계약](reports/P1234-fixes-2026-09-13.md)을 우선 적용한다. 월령 exact 보존, 총 필요량/보유량 분리, 미검토 품목 unknown, 편집 검증과 예산 포함 feasible로 변경됐다. 기존 보고서의 정상 통합 결과 중 무해당 판정에 의존한 자동 선택은 현재 결과로 재사용하지 않는다.

## CURRENT BASELINE / SYNC DELTA (2026-09-13)

Read [integration audit](reports/sync-2026-09-13.md); this delta overrides obsolete baseline assumptions below.

- Shared ProductRepo upsert/variant/offer/observation methods and db/seed_catalog.py now work for51 PC products. Extend/reuse them; do not replace with another repository implementation.
- Existing db/seed.py / setup_all.py seed domains and PC after migrations. P0 must adapt their legacy source/unit/domain_version SQL. Baby catalog/rules are still absent and baby.yaml status=stub refers to recommendation, not empty questions.
- Keep latest age_months storage + age_stage display adapter; need canonicalization maps free-text subterms (이유식/목욕) to9 frontend areas. Do not feed representative chip values directly to precise eligibility rules.
- Latest PC product lookup uses model/name and variant default; baby must use exact product+variant keys and explicit corpus. Shared latest fallback URL example.com and synthetic prices are not real purchase destinations.

## EXECUTION

Implement this task, not a plan-only response. Read [CONTRACTS.md](CONTRACTS.md) first. Repository root is `/home/ubuntu/skn_final` in the authoring environment; resolve paths from the actual checkout. Ignore `개발 역할 분담`. This is a continuation work order; inspect and reuse existing upstream/stash implementations, then implement missing acceptance behavior. Verify dependency reports against current code before proceeding.

## READ FIRST

- `scripts/generate_baby_products.py`
- `가상제품_생성기_사용법.md`
- `유아용품_가상제품_레코드예시_스펙표.md`
- `config/categories/baby.yaml`
- `data/synthetic_manuals/stroller_example.json`
- `src/repo/product_repo.py`
- `src/engine/stage2_requirement.py`
- `src/engine/stage3_0_candidates.py`

## EDIT SURFACE

- `scripts/유아용품_가상제품_스펙사전_v1.json (restore/create)`
- `scripts/generate_baby_products.py`
- `scripts/seed_baby_catalog.py (new)`
- `config/categories/baby.yaml`
- `config/baby_requirement_rules.yaml (new)`
- `src/repo/product_repo.py`
- `src/engine/stage2_requirement.py`
- `src/engine/stage3_0_candidates.py`
- `tests/test_baby_catalog.py (new)`
- `tests/test_baby_requirements.py (new)`

Shared-file changes follow CONTRACTS dependency protocol. Do not overwrite unrelated code; preserve PC regression behavior.

## OBJECTIVE / INTERFACE

Build deterministic, labeled synthetic catalog with exact option identities and a typed needs engine. Consumer signatures to implement (or equivalent explicit adapters):

```python
build_baby_requirements(conditions, domain_snapshot) -> list[BabyRequirement]
get_baby_candidates(conn, requirements, *, corpus) -> dict[requirement_id, list[BabyCandidate]]
seed_catalog(conn, records, *, dataset_version) -> SeedReport
```

Deliver default seed input `data/baby/catalog_demo_v1.json` and make the documented seed CLI use it when --input is omitted. Commit deterministic synthetic data only; record generation seed and manifest hash.

No HTTP/Principal dependency: accept P0 normalized conditions. No recommendation-scenario JSON and no price jitter on each read. Production selection reads SQL.

## DATA CONTRACT

Each record: dataset_version, is_synthetic, product_key, variant_key, name, brand, category_code, slot_key, market, language, corpus, pack_quantity, unit_code/unit_qty, attributes, offer{merchant_key,external_offer_id,price,currency,observed_at,stock_status,purchase_url?}, facts[{key,value,unit,evidence_ref?,verification_status}], manual_ref?. Real and synthetic namespaces distinct. Missing purchase URL is null, not example checkout link.

- Existing generator promises 23 families: restore a compatible dictionary and validate all accepted families, not silently narrow CLI. Initial service fixtures can use a reviewed subset but every one of nine need areas has declared rules or explicit data_gap.
- Include existing SYN-STROLLER-001 / SYN-STROLLER-001-GREY exact identity for RAG fixture. Additional synthetic options: valid alternative, missing identifier, over-budget, active synthetic recall, unknown certification, newborn-inapplicable seat. No fake KC number presented as real.
- Rules are versioned data: rule_key, slot_key, needs[], mode, age window, mandatory, required_qty/unit, timing, applicability predicates, source_kind (synthetic_demo/curated_real), source_ref and review_status. Demo age windows are test rules, not medical advice. Unknown health condition is not a treatment recommendation.

## IMPLEMENTATION

1. Inspect actual generator input schema before restoring dictionary. Add JSON/schema validation and deterministic seed option. Use source specs already in repository; do not invent real product facts. For missing verified data use explicit unknown or synthetic fixtures.
2. Provide seed CLI with input/dataset-version/corpus arguments and dry-run validation. Transactional idempotent upsert product→option→merchant→offer→observation; uniqueness on stable keys. Same observation identity/hash no duplicate; changed observation creates new historical record, never overwrite old price.
3. Resolve product.category_id one canonical category; need areas can map many slots through YAML. Store pack unit and purchase quantity separately. Preserve exact product+variant+market in manual mapping.
4. Implement need rules for normalized born/prenatal inputs. Ordering stable by timing/mandatory/slot_key. Use condition reference date in snapshot for any date-dependent due calculation; no unrecorded current-date effect.
5. Owned items match canonical slots, ask/return unresolved if name ambiguous. Persist owned rows and fulfilled requirement references through a separate repository operation; pure rule function emits plan changes. Partial owned quantity splits remaining purchase requirement with same group_key and no double counting.
6. Query only allowed corpus, in-scope options, valid priced observations and acceptable stock. Missing price/data returns diagnostic gap, not free item. Candidate constructor must not default safety to pass (old Candidate default is unsuitable).
7. Record every required but unsupported slot in unresolved/missing list, even if other categories have candidates. Supply deterministic fixtures consumed by P3/P4/P5.

## ACCEPTANCE

- CA01 seed twice same file produces same IDs/counts; updated price preserves old observation; invalid input rolls back.
- CA02 8-month fixture needs feeding+outing, owned stroller → stroller requirement fulfilled owned, remaining feeding slots stable; prenatal differs without fabricated age.
- CA03 2 packs of 40 diapers means qty=2, unit_qty=40, not 80 charged packs; two variants remain independently queryable.
- CA04 missing dictionary now resolved for CLI; invalid units/missing keys fail before DB write.
- CA05 one unavailable need area remains visible as data_gap; no substitution from PC/other corpus.
- CA06 all fixtures label synthetic and RAG identity matches exact stroller option.

## VERIFY

```bash
uv run python scripts/seed_baby_catalog.py --help
uv run python scripts/seed_baby_catalog.py --corpus synthetic --dataset-version baby-demo-v1
uv run python -m pytest -q tests/test_baby_catalog.py tests/test_baby_requirements.py
```

Deliver command flags exactly as documented or update this spec+all consumers. Report row counts, IDs, fixture path and generated rule snapshot/hash for P3/P4/P5.

## EXIT

All acceptance cases below must have real observed results. Write the completion report specified in CONTRACTS. Update the parent status document only for behavior actually verified. If a dependency or external gate remains unmet, report partial/blocked with its exact failing check; do not replace it with a fixed successful response.
