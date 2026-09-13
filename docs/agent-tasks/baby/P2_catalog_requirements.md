---
task_id: "P2"
status: "partial_shared_catalog"
entry_gate: "ready_after_dependencies"
depends_on: ["P0"]
contract_version: 2
report_path: "docs/agent-tasks/baby/reports/P2.md"
---

# P2 — 유아 카탈로그·단위·필요 품목 규칙

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
