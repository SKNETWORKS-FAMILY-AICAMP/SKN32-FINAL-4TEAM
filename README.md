# TrueFit — Purpose-Driven Shopping Planner

**English** · [한국어](README.ko.md)

TrueFit turns a goal — *"a quiet gaming PC under ₩2,000,000"*, *"everything an 8-month-old needs for going out"* — into a concrete, budget-checked shopping list, and shows its work: why each item was chosen, which compatibility or safety checks passed or are still open, and what the review data actually shows about each product.

- **Two domains.** PC builds (set optimization + compatibility verification) and baby products (per-item safety gating + budget allocation).
- **Agents where judgment needs language, code where it needs numbers.** Two [Strands Agents SDK](https://strandsagents.com/) agents run the free-text conversation and the result-screen edits through tool calls; ranking, verification scores, budget math and every persisted value come from code.
- **Evidence, not scores.** Review analysis reports *observed facts* ("100 of 200 reviews landed within 7 days — category median 5.5%") and never a "fake review" verdict. Before-you-buy checks cite a care-guide passage. Explanations are generated from stored facts only.

What it is **not**: it is not a store (purchase links go to sellers), the demo catalog prices and reviews are **synthetic** and labeled as such in the UI (`data_notice`), and it does not decide whether a review is fake or a part is "better".

> Snapshot of branch `feat/sllm-work` on **2026-09-14** (upstream `develop` + 13 commits). Built for the AWS *Agents for Humans* hackathon; development continues to 2026-10-26. Sections marked *(Korean)* link to team documents written in Korean.

## What you see

Landing → Category → Conditions chat → Results → Confirm → Report, plus login/sign-up/account. Every screen is a separate static page under `frontend/` served by the API on the same origin; every value comes from the API and the database — no demo accounts, no client-side fake data. The UI has a Korean/English toggle; in an English session the server also writes its questions, chips, progress steps and explanations in English and reads unit-less budgets as US dollars (`USD_KRW_RATE`, fixed).

| Screen | Page | What happens |
|---|---|---|
| Category | `category.html` | Pick PC (new build / upgrade) or baby (expecting / born). Creates a guest session cookie — no login needed to get a recommendation |
| Conditions | `conditions.html` | Mixed chat: chips for required fields, free text for anything else (`POST /session/{id}/message` → conditions agent when enabled, keyword rules otherwise). Upgrade mode accepts a text spec file |
| Results | `results.html` | Items per slot with price, budget share, **reason**, **before-you-buy checks**, and a review line. Swap from alternatives, change quantity/timing, remove/restore, or type a request ("cheaper CPU") → result agent when enabled. "Show the process" opens `logs.html` |
| Confirm | `confirm.html` | Name, planned purchase date, target amount, memo (pre-filled from the result). Login required from here on; a guest's baskets merge into the account on sign-up |
| Report | `report.html` | Confirmed snapshot with seller links and an optional target-price watch |

## Architecture

```mermaid
flowchart LR
  subgraph Browser["Browser — frontend/ (10 static pages, KO/EN)"]
    UI["TF_API fetch wrapper<br/>httpOnly cookies only"]
  end
  subgraph API["FastAPI — src/api.py (38 operations)"]
    S["/session · conversation, recommend, result edits"]
    L["/lists · confirm, report, price watch"]
    A["/auth · email + password, JWT cookie"]
    RV["/reviews · summary (relation axis)"]
  end
  subgraph Agents["Strands Agents SDK (opt-in)"]
    CA["Conditions agent<br/>set_condition · add_extra_condition · clear_condition"]
    RA["Result agent<br/>list_alternatives · swap · set_qty · set_timing<br/>remove_or_restore · explain"]
  end
  subgraph Engine["Recommendation engine — src/engine"]
    E["[1] intent → [2] requirement → [3-0] candidates → [3-A] hard filter<br/>→ [3-B] rank → [4] optimize ⇄ [3-C] verify → [5] explain"]
  end
  subgraph Evidence["Evidence sources"]
    RX["Review relation axis<br/>Amazon Reviews'23 batch → JSON"]
    CG["Part care-guide RAG<br/>18 guides, in-memory embeddings"]
    MR["Manual search provider<br/>local-file, outside PostgreSQL"]
  end
  DB[("PostgreSQL 16<br/>10 schemas · 38 tables")]
  LLM["OpenAI API<br/>chat + embeddings"]
  UI --> API
  S --> CA & RA & Engine
  Engine --> RX & CG & MR
  API --> DB
  CA & RA --> LLM
  Engine -- "[3-C] issue sentences · [5] explanation" --> LLM
  CG --> LLM
```

The engine runs the same stages for both domains up to ranking, then branches: **PC** optimizes the set first and verifies it as a whole (below the confidence threshold it swaps a candidate and re-runs — `computer_research` shows one such round); **baby** verifies each item first (manual applicability, recall, certification) and then allocates the budget across mandatory and optional items. `POST /session/{id}/recommend` returns `202` immediately and the run persists its requirements, candidates, checks and explanation to PostgreSQL; `GET …/result` polls.

## Agents (Strands Agents SDK)

| Agent | Endpoint | Tools | Boundary |
|---|---|---|---|
| **Conditions agent** — `src/agent/conditions_agent.py` | `POST /session/{id}/message` | `set_condition`, `add_extra_condition`, `clear_condition` | May only touch fields in `config/categories/<cat>.yaml` `slot_schema`; enum/type/nullability is validated in code and a violation is returned to the model as an error to fix. Never touches the DB — patches are written by `session_service` with the same origin as the rule path. Asks the next missing required question |
| **Result agent** — `src/agent/result_agent.py` | `POST /session/{id}/result-message` | `list_alternatives`, `swap`, `set_qty`, `set_timing`, `remove_or_restore`, `explain` | Wraps existing service functions; optimization, verification and ranking stay in the engine. `explain` returns stored reasons, issues and review observations only — no "is this review fake?", no "is this part better?" |

Design rule kept throughout: **verdicts and numbers come from code; the LLM narrates.** The same OpenAI-backed `call_llm` also writes the [3-C] verification issue sentences and the [5] explanation from facts the engine hands it. Everything runs without a key in `MOCK_MODE=1` — you then see `[MOCK] …` placeholder sentences and the rule-based paths (keyword extraction; "slot + cheaper/better" edits).

Turn the agents on with all of `MOCK_MODE=0 · LLM_PROVIDER=openai · LLM_MODEL · OPENAI_API_KEY` plus `CONDITIONS_AGENT=1` / `RESULT_AGENT=1`. Design notes *(Korean)*: [conditions agent](docs/조건대화_에이전트_strands.md) · [result agent](docs/결과화면_에이전트_strands.md).

## Quick start

Python **3.11** and [`uv`](https://docs.astral.sh/uv/). Configuration is read from process environment variables, with `.env` in the project root as a fallback (`.env.example` lists them).

### A. Console demo — no database, no API key

```bash
uv sync --locked
uv run python main.py --list
uv run python main.py computer_pass        # 8 slots, passes verification in one round
uv run python main.py computer_research    # injected score 72 → swap candidate → 86
uv run python -m pytest -q                 # 264 passed, 162 skipped without a DB (see Tests)
```

The console pipeline runs from scenario files in `data/scenarios/` with mock LLM output and **injected** verification scores; `stage4_optimize.py` picks per-slot candidates approximately. Do not read its confidence, contributions or synthetic prices as real product quality, market prices or compatibility.

### B. Full stack — web UI + PostgreSQL

```bash
cp .env.example .env                        # defaults: MOCK_MODE=1, agents off
docker compose up -d db                     # pgvector/pgvector:pg16 on localhost:5432
export DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit
uv run python db/setup_all.py               # 15 migrations · domains · 51 PC parts · 153 review summaries
uv run python scripts/generate_and_seed_baby_catalog.py   # 188 synthetic baby products (baby domain)
uv run uvicorn src.api:app --reload --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000> — the API serves the frontend on the same origin, so no second server. Swagger UI is at `/docs`; `GET /health` only says the process is up, not that the DB is reachable. [`db/README.md`](db/README.md) *(Korean)* is the canonical DB setup guide and includes a conda route without Docker. Every developer uses a local DB; there is no shared one.

### C. Real LLM and agents

```ini
MOCK_MODE=0
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=...
CONDITIONS_AGENT=1
RESULT_AGENT=1
```

The test suite reads `.env` too — run it with `MOCK_MODE=1 uv run python -m pytest -q` or the result-agent tests will call OpenAI.

### D. Deploy with Docker

```bash
docker compose up -d --build                     # db + api (image: Dockerfile)
docker compose exec api python db/setup_all.py   # first run
```

The image does not include `scripts/`, so seed the baby catalog from the host against the published port. Set `JWT_SECRET` (the app refuses the dev default when `APP_ENV=production`), `COOKIE_SECURE=1` behind HTTPS, and `ALLOWED_ORIGINS` only if the UI is served from another origin — the API is same-origin by design and answers `403` to mutating requests carrying a foreign `Origin`.

## What works today, and what does not

| Area | Working | Limits |
|---|---|---|
| PC recommendation (web) | Guest session → conditions → run → result with reasons, checks, review line, alternatives, swap, quantity/timing, result chat → confirm → report → price watch, all persisted | Catalog of 51 parts with **synthetic prices**; compatibility checks are approximations (socket, power, size); a swap does not re-run verification (the UI offers "another build" for that) |
| Baby recommendation (web) | Conditions (age, needs, health/skin, owned items, weight, sitting) → run → per-item candidates with safety checks → budget allocation | With the shipped synthetic catalog **no candidate passes gating** (no reviewed safety rule per category; active-recall flags), so the basket ends *done* with 0 selected items and the message "mandatory items cannot be filled within budget" — the mechanism runs, the data does not yet let it choose |
| Conversation | Chips + free text; Strands conditions agent (opt-in) reflects "extra conditions/changes" that keyword rules miss; English sessions fully in English | Rule path only knows fixed keywords; the agent needs an OpenAI key |
| Auth & lists | Email + password (argon2), httpOnly JWT cookie, guest → account merge, rename/delete, soft withdrawal | Email verification and password-reset mail are deferred (10/26); `/auth/request-code`, `/auth/verify` are stubs (`501`) |
| Review evidence | Relation/behavior-axis facts for 25 of 51 demo parts, in [3-B] ranking (demotion, never exclusion), [5] explanation and `GET /reviews/summary` | No manipulation labels → **no detection rate and no cleaned rating** (`cleaned_rating` is always null — [decision 0001](docs/decisions/0001-정제-후-평점을-판정기-없이-내지-않는다.md) *(Korean)*). Review **writing** is out of demo scope |
| RAG | *Before you buy* checks cite 18 synthetic part care guides via in-memory embeddings; baby manuals are published to a local-file search provider (`BABY_SEARCH_PROVIDER=local-file`; 5 chunks, 21/21 regression queries) that verifies seat conditions from reviewed sentences only | The PostgreSQL `rag` schema was dropped (migration 0011) after mentor review — chunks and vectors do not belong in the RDB. A hosted vector store is planned but not configured; without a provider the eligibility is *unknown*, never a silent fallback |
| Database | 10 schemas / 38 tables after the 58 → 38 reduction, FK/UNIQUE/CHECK, `updated_at` triggers, one-shot `db/setup_all.py`, RDS-compatible SQL | Optimistic locking, state-transition and cross-schema invariants are enforced in services, not the DB |
| Data tools | Amazon Reviews'23 batch, synthetic catalogs and manuals, spec scraper | No live price or spec feed; notification and feedback-learning workers are stubs |

## API surface

38 operations in the OpenAPI document (`/docs`). Cookie auth: `truefit_guest` for anonymous sessions, `truefit_session` (JWT) after login.

| Group | Operations | State |
|---|---|---|
| `/session` (14) | `POST /session`, `GET /session/{id}`, `POST …/category`, `PATCH …/slot`, `POST …/message`, `…/answer`, `…/reset`, `…/spec-file`, `POST …/recommend` (202), `GET …/result`, `PATCH …/items/{item_id}`, `GET …/items/{item_id}/alternatives`, `POST …/items/{item_id}/swap`, `POST …/result-message` | Working, no login required |
| `/lists` (6) | `GET /lists`, `PATCH /lists/{id}`, `DELETE /lists/{id}`, `POST …/confirm` (with `If-Match` lock version), `GET …/report`, `POST …/alert` | Working; confirm/report/alert require login |
| `/auth` (10) | `signup`, `login`, `logout`, `GET/PATCH me`, `password`, `withdraw`, `email-availability` | Working. `request-code`, `verify` → `501` (reserved for email verification) |
| `/reviews` (5) | `GET /reviews/summary/{product_key}` (engine key, summary key or ASIN) | Working. `pending` / `part` / `publish` read and write review drafts against the DB; `build` → `501`. Review writing is out of demo scope |
| `/dev` (2) | `GET /dev/scenarios`, `POST /dev/run` | Scenario pipeline without a DB; remove or guard before exposing publicly |
| `/health` | `GET /health` | Process liveness only |

Errors use one envelope: `{"error": {"code", "message", "field"}}`. The contract the frontend is built against is [`docs/frontend_외부수정요청.md`](docs/frontend_외부수정요청.md) *(Korean)*.

## Review evidence — relation and behavior axis

Without reading review text, the batch looks at **who reviewed what, when** and produces per-product observations that anyone can check or refute: share of reviews landing within 7 days, reviewers shared with other products, account composition — each against the median of the same product category as control. Source: Amazon Reviews'23 (Electronics: 43.9 M reviews, ≈12 GB, ≈6 min). Raw `.jsonl` files are not in the repository and `data/amazon23/` is git-ignored.

```bash
uv sync --group review-analysis --group test          # pandas · numpy · scipy · httpx
uv run python scripts/amazon23_edges.py <Electronics.jsonl> --cat electronics      # reviews → edge table (text dropped)
uv run python scripts/amazon23_meta_slim.py <meta_Electronics.jsonl> --cat electronics
uv run python scripts/map_parts_to_asin.py            # data/parts_list.csv ↔ ASIN (25/51 mapped; the rest launched after 2023-09)
uv run python -m src.workers.review_cleanse_worker data/amazon23/electronics_edges.tsv \
    --meta data/amazon23/electronics_meta.tsv --category "Computer Components|Data Storage" \
    --out data/amazon23/pcparts_product_risk.json
uv run python -m src.workers.review_cleanse_worker --lookup amd-ryzen-5-5600   # one product's card
```

- Where the output JSON is absent, `ProductRiskStore` is `None` and every consumer shows *no observation* — it never invents a value.
- `GET /reviews/summary` returns the observed block and, separately, a synthetic demo block flagged `is_synthetic: true`; the UI must keep the flag visible.
- What a future collector must capture on day one (author hash, posting time, variant-level subject) is in [`docs/review_collector.md`](docs/review_collector.md) *(Korean)*; the stored columns are [decision 0002](docs/decisions/0002-review_summary에-작성자-해시와-게시시각을-둔다.md) *(Korean)*. Nothing can be back-filled later.

## Data and tools

| Tool | Purpose |
|---|---|
| `db/setup_all.py` | Migrations + reference data + PC catalog + review summaries, idempotent |
| `scripts/generate_and_seed_baby_catalog.py` | Deterministic synthetic baby catalog (188 products, 18 item types) → DB upsert; `--dry-run` validates without a DB |
| `scripts/generate_baby_manual.py` | Rule-based **partial** product manual from a JSON spec (`data/synthetic_manuals/stroller_example.json`) with fact ledger, citations, hashes and validation — never invents operating or safety instructions. [Details](docs/synthetic_manual_generator.md) *(Korean)* |
| `scripts/rag_manual.py ingest\|query\|evaluate --provider local-file` | Publish a generated manual to the local-file search provider (`.baby-search-index/`), query it, run the 21-case regression. The API uses the same index when `BABY_SEARCH_PROVIDER=local-file` is set; unset means *unconfigured* |
| `scripts/build_specs.py` | First-party spec scraper for CPU/GPU/mainboard with source URLs (1 req/s, robots.txt, cache). Most target sites render client-side, so expect a manual to-do list. [Notes](scripts/README.md) *(Korean)* |
| `scripts/gen_review_summaries.py` | Synthetic review summaries for the demo (`data/review_summaries.json`) — not real reviews |
| `scripts/import_review_analysis.py` · `evaluate_review_signals.py` | Load a file-based review analysis into `evidence.*`; research-only evaluation that refuses leaky splits |
| `scripts/check_baby_readiness.py` | Read-only readiness report of a baby DB (JSON, no connection string) |

Data actually tracked in the repo: `data/parts_list.csv` (51 parts), `data/parts_asin_map.csv`, `data/parts_specs*.{csv,json}`, `data/pc_care_guides.json`, `data/review_summaries.json` (synthetic), `data/review_suspect_counts.json`, `data/baby/catalog_demo_v1.json`, two scenarios, one manual input.

## Repository layout

```text
main.py                       console pipeline entry point (scenario files, mock LLM)
src/
  api.py, routers/, schemas.py FastAPI app, 5 routers, API contract; serves frontend/
  services/                   session · recommendation · list · auth · review · feedback
  agent/                      Strands agents: conditions_agent.py, result_agent.py
  engine/                     stages [1]–[6] (+ slot_rules keyword extraction, prompts, lang)
  pipeline.py                 console orchestration of the stages
  rag/                        care_guides (in-memory RAG) · provider (external search boundary) ·
                              ingestion · evidence_search · verification · contracts
  repo/                       SQL repositories (plan, engine, product, user, review, rag, …)
  workers/                    review_cleanse_worker + relation_axis (batch); other workers are stubs
  auth/, db/, config.py       JWT/argon2/origin check · psycopg pool · env config
config/categories/            computer.yaml · baby.yaml (slots, questions, modes) + baby rules
frontend/                     10 pages, css/, js/ (api.js · core.js · planner-shell.js · i18n.js · pages/)
db/                           migrate.py · 15 migrations · seed*.py · setup_all.py · README.md
scripts/                      catalog/manual generators · RAG CLI · Amazon'23 batch · spec scraper
data/                         parts list, specs, care guides, scenarios, synthetic inputs
docs/                         DB spec & diagram, API contract, agent notes, decisions/, meeting-derived reports
generated/                    example manual, RAG evaluation outputs
tests/                        pipeline · agents · HTTP flows · services · SQL/migration checks
Dockerfile, docker-compose.yml
```

## Tests and what was verified

```bash
MOCK_MODE=1 uv run python -m pytest -q                       # without DATABASE_URL: DB tests skip
DATABASE_URL=postgresql://…/<disposable> MOCK_MODE=1 uv run python -m pytest -q   # after setup_all + baby seed
```

Measured on 2026-09-14 for this README:

| Run | Result |
|---|---|
| No database | **264 passed, 162 skipped, 1 failed** in <1 s. The failure pins the migration list to an older `develop` commit and flags `0014_candidate_checks.sql` as drift — the test is stale, not the schema |
| Fresh database (`setup_all.py` + baby seed), mock LLM | **402 passed, 17 failed, 8 skipped** in 8 s. Failures: 6 baby-track HTTP tests written against a pre-merge result shape (`status` per item), 7 auth-hardening acceptance tests not yet satisfied (rate limit on `email-availability`, lock-counter reset, JWT invalidation right after a password change, consent-timestamp erasure on withdrawal), 2 double-confirm/lock-version conflict tests, 1 requirement-shape test, and the stale migration pin above. Skips: pandas not installed (2), tests that demand their own throwaway DB (6) |
| Console | `computer_pass`, `computer_research` finish; results table + review observation lines |
| HTTP, PC domain | Session → conditions from free text ("게임용으로 200만원, 조용했으면") → recommend → `done`, 8 items, ₩1,439,000 of ₩2,000,000, confidence 94, checks and review lines present → result chat swaps the CPU → alternatives listed → review summary returns *unavailable* honestly for an unmapped part |
| HTTP, baby domain | Three need sets (going out, feeding, sleep) each reach `done`; 19–26 candidates listed with their check text; 0 selected (see limits) |
| RAG | `rag_manual.py ingest/query/evaluate --provider local-file`: 5 chunks, extractive answer with `verification_status: partial`, 21/21 |

Not verified: real-LLM output quality over many sessions, production PostgreSQL load, real product safety, prices or compatibility, and the Docker image on AWS.

## Known gaps and next steps

1. **Baby catalog that can pass its own gates** — reviewed safety rules per category and certification/recall data on the synthetic products, so the allocation step has something to choose from.
2. **Hosted vector search** behind `src/rag/provider.py` (the boundary and a local-file implementation exist); then wire manual evidence into PC checks too.
3. Auth hardening the tests already describe: rate limiting, lock-counter semantics, immediate JWT invalidation, full anonymization on withdrawal; email verification and password reset (deferred to 10/26).
4. Re-verify after a swap; real spec/price feeds and exact compatibility rules; PC hard filters beyond the current approximations.
5. Reviews: a collector that captures author hash, posting time and variant subject from the first record; a human-labeling protocol (queue origin and random control share fixed **before** the first label); only then a cleaned rating.
6. Price tracking, notifications and feedback learning — workers exist as stubs; batch learning is on hold.

## License and documents

MIT — see [`LICENSE`](LICENSE).

- [`db/README.md`](db/README.md) — DB setup (canonical), migration list, AWS/RDS compatibility notes *(Korean)*
- [`docs/db/table_spec.md`](docs/db/table_spec.md) — table specification; [structure diagram](docs/db/database-structure-overview.png) · [SVG](docs/db/database-structure-overview.svg) · [reduction proposal](docs/db/db_schema_reduction_proposal_2026-09-12.md) *(Korean)*
- [`docs/frontend_외부수정요청.md`](docs/frontend_외부수정요청.md) — frontend ↔ backend API contract *(Korean)*; [`frontend/CLAUDE.md`](frontend/CLAUDE.md) — page map and frontend rules *(Korean)*
- [`docs/decisions/`](docs/decisions/README.md) — decisions that are hard to reverse, with the alternatives that were tried *(Korean)*
- [`docs/review_analysis_contract.md`](docs/review_analysis_contract.md) · [`docs/review_collector.md`](docs/review_collector.md) · [`docs/review_module_handoff.md`](docs/review_module_handoff.md) — review analysis file contract, collector requirements, module hand-off *(Korean)*
- [`docs/agent-tasks/baby/`](docs/agent-tasks/baby/README.md) — baby-domain work packages P0–P9 and their acceptance reports *(Korean)*
- [`docs/synthetic_manual_generator.md`](docs/synthetic_manual_generator.md) — manual generator input contract; [`docs/rag_implementation.md`](docs/rag_implementation.md) describes the **removed** pgvector design and is kept for history *(Korean)*
