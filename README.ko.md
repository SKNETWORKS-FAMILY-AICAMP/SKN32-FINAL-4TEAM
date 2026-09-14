# TrueFit — 목적성 쇼핑 플래너

[English](README.md) · **한국어**

TrueFit은 목적 — *"200만 원 이하의 조용한 게임용 PC"*, *"8개월 아기 외출 준비물 전부"* — 을 예산까지 맞춘 구체적인 구매 목록으로 바꾸고, 그 근거를 보여줍니다. 왜 이 품목인지, 어떤 호환·안전 검사를 통과했고 무엇이 아직 열려 있는지, 리뷰 데이터가 그 상품에 대해 실제로 무엇을 보여주는지.

- **두 도메인.** PC 조립(세트 최적화 + 호환성 검증)과 유아용품(품목별 안전 게이트 + 예산 배분).
- **말이 필요한 판단은 에이전트가, 숫자가 필요한 판단은 코드가.** [Strands Agents SDK](https://strandsagents.com/) 에이전트 두 개가 자유 텍스트 대화와 결과 화면 편집을 도구 호출로 처리하고, 순위·검증 점수·예산 계산·저장되는 모든 값은 코드가 만듭니다.
- **점수가 아니라 근거.** 리뷰 분석은 *관측 사실*("리뷰 200건 중 100건이 7일 안에 몰림 — 부류 중앙값 5.5%")만 내고 "허위 리뷰" 판정은 하지 않습니다. 구매 전 확인은 사용 가이드 문장을 인용합니다. 설명은 저장된 사실에서만 생성합니다.

TrueFit이 **아닌 것**: 상점이 아닙니다(구매 링크는 판매처로 갑니다). 데모 카탈로그의 가격·리뷰는 **합성 데이터**이며 화면에 그렇게 표시됩니다(`data_notice`). 리뷰가 허위인지, 어떤 부품이 "더 좋은지"는 판정하지 않습니다.

> **2026-09-14** `feat/sllm-work` 브랜치 기준(upstream `develop` + 13 커밋). AWS *Agents for Humans* 해커톤을 위해 만들었고 개발은 2026-10-26까지 이어집니다.

## 화면 흐름

랜딩 → 카테고리 → 조건 대화 → 추천 결과 → 리스트 확정 → 리포트, 그리고 로그인·회원가입·회원정보. 모든 화면은 `frontend/` 아래 별도 정적 페이지이고 API가 같은 오리진에서 서빙합니다. 모든 값은 API와 DB에서 옵니다 — 데모 계정도, 화면용 가짜 데이터도 없습니다. UI에 한국어/영어 토글이 있고, 영어 세션이면 서버도 질문·칩·진행 단계·설명을 영어로 쓰며 단위 없는 예산 숫자를 달러로 읽습니다(`USD_KRW_RATE`, 고정 환율).

| 화면 | 파일 | 하는 일 |
|---|---|---|
| 카테고리 | `category.html` | PC(새 조립 / 업그레이드) 또는 유아용품(출산 예정 / 출생) 선택. 게스트 세션 쿠키가 생기며 추천까지는 로그인이 필요 없음 |
| 조건 대화 | `conditions.html` | 칩과 자유 입력이 섞인 대화. 필수 항목은 칩으로, 나머지는 자유 텍스트로(`POST /session/{id}/message` → 켜져 있으면 조건 에이전트, 아니면 키워드 규칙). 업그레이드 모드는 텍스트 사양 파일 첨부 가능 |
| 추천 결과 | `results.html` | 슬롯별 품목과 가격·예산 비중·**추천 이유**·**구매 전 확인**·리뷰 관측 한 줄. 대안에서 교체, 수량·구매 시점 변경, 빼기/되돌리기, 또는 자유 요청("CPU 더 저렴한 걸로") → 켜져 있으면 결과 에이전트. "추천 과정 보기"는 `logs.html` |
| 리스트 확정 | `confirm.html` | 이름·구매 예정일·목표 금액·메모(결과에서 미리 채움). 여기서부터 로그인 필요. 게스트의 장바구니는 가입 시 계정으로 합쳐짐 |
| 리포트 | `report.html` | 확정 스냅샷과 판매처 링크, 선택 사항인 목표가 추적 |

## 아키텍처

```mermaid
flowchart LR
  subgraph Browser["브라우저 — frontend/ (정적 페이지 10개, KO/EN)"]
    UI["TF_API fetch 래퍼<br/>httpOnly 쿠키만"]
  end
  subgraph API["FastAPI — src/api.py (작업 38개)"]
    S["/session · 대화, 추천 실행, 결과 편집"]
    L["/lists · 확정, 리포트, 목표가 추적"]
    A["/auth · 이메일+비밀번호, JWT 쿠키"]
    RV["/reviews · 요약(관계 축)"]
  end
  subgraph Agents["Strands Agents SDK (opt-in)"]
    CA["조건 에이전트<br/>set_condition · add_extra_condition · clear_condition"]
    RA["결과 에이전트<br/>list_alternatives · swap · set_qty · set_timing<br/>remove_or_restore · explain"]
  end
  subgraph Engine["추천 엔진 — src/engine"]
    E["[1] 의도 → [2] 요구사양 → [3-0] 후보 → [3-A] 하드필터<br/>→ [3-B] 순위 → [4] 최적화 ⇄ [3-C] 검증 → [5] 설명"]
  end
  subgraph Evidence["근거 소스"]
    RX["리뷰 관계·행동 축<br/>Amazon Reviews'23 배치 → JSON"]
    CG["부품 사용 가이드 RAG<br/>18건, 인메모리 임베딩"]
    MR["설명서 검색 제공자<br/>local-file, PostgreSQL 밖"]
  end
  DB[("PostgreSQL 16<br/>스키마 10 · 테이블 38")]
  LLM["OpenAI API<br/>chat + embeddings"]
  UI --> API
  S --> CA & RA & Engine
  Engine --> RX & CG & MR
  API --> DB
  CA & RA --> LLM
  Engine -- "[3-C] 쟁점 문장 · [5] 설명" --> LLM
  CG --> LLM
```

엔진은 두 도메인 모두 순위까지 같은 단계를 거친 뒤 갈라집니다. **PC**는 세트를 먼저 최적화하고 세트 전체를 검증합니다(신뢰도 문턱 아래면 후보를 바꿔 재실행 — `computer_research`가 그 한 라운드를 보여줍니다). **유아용품**은 품목마다 먼저 검증하고(설명서 적용 조건·리콜·인증) 필수·선택 품목에 예산을 배분합니다. `POST /session/{id}/recommend`는 즉시 `202`를 돌려주고, 실행은 요구사양·후보·검사·설명을 PostgreSQL에 저장하며 `GET …/result`로 폴링합니다.

## 에이전트 (Strands Agents SDK)

| 에이전트 | 엔드포인트 | 도구 | 경계 |
|---|---|---|---|
| **조건 에이전트** — `src/agent/conditions_agent.py` | `POST /session/{id}/message` | `set_condition`, `add_extra_condition`, `clear_condition` | `config/categories/<cat>.yaml`의 `slot_schema`에 있는 필드만 만질 수 있음. enum·타입·nullable은 코드가 검사하고, 틀리면 오류 문장을 모델에 돌려줘 고쳐 부르게 함. DB는 만지지 않음 — 패치는 `session_service`가 규칙 경로와 같은 origin으로 씀. 비어 있는 다음 필수 항목을 이어서 물음 |
| **결과 에이전트** — `src/agent/result_agent.py` | `POST /session/{id}/result-message` | `list_alternatives`, `swap`, `set_qty`, `set_timing`, `remove_or_restore`, `explain` | 기존 서비스 함수를 감쌈. 최적화·검증·순위는 엔진 몫. `explain`은 저장된 이유·쟁점·리뷰 관측만 옮김 — "이 리뷰 조작인가?", "이 부품이 더 좋은가?"는 없음 |

끝까지 지킨 설계 규칙: **판정과 수치는 코드, LLM은 서술.** 같은 OpenAI 기반 `call_llm`이 엔진이 넘긴 사실로 [3-C] 검증 쟁점 문장과 [5] 설명도 씁니다. `MOCK_MODE=1`이면 키 없이 전부 돌아갑니다 — 그때는 `[MOCK] …` 자리표시 문장과 규칙 경로(키워드 추출, "슬롯 + 저렴/좋은" 편집)를 보게 됩니다.

에이전트를 켜려면 `MOCK_MODE=0 · LLM_PROVIDER=openai · LLM_MODEL · OPENAI_API_KEY` 넷이 다 있고 `CONDITIONS_AGENT=1` / `RESULT_AGENT=1`이어야 합니다. 설계 문서: [조건 대화 에이전트](docs/조건대화_에이전트_strands.md) · [결과 화면 에이전트](docs/결과화면_에이전트_strands.md).

## 빠른 시작

Python **3.11**과 [`uv`](https://docs.astral.sh/uv/). 설정은 프로세스 환경변수로 읽고, 없으면 프로젝트 루트의 `.env`를 씁니다(`.env.example`에 목록이 있습니다).

### A. 콘솔 데모 — DB도 API 키도 없이

```bash
uv sync --locked
uv run python main.py --list
uv run python main.py computer_pass        # 8개 슬롯, 검증 1회 통과
uv run python main.py computer_research    # 주입된 점수 72 → 후보 교체 → 86
uv run python -m pytest -q                 # DB 없이 264 passed, 162 skipped (아래 테스트 절)
```

콘솔 파이프라인은 `data/scenarios/`의 시나리오 파일로 돌며 LLM 출력은 목, 검증 점수는 **주입값**입니다. `stage4_optimize.py`는 슬롯별 후보를 고르는 근사 구현입니다. 신뢰도·기여도·합성 가격을 실제 상품 품질·시세·호환성으로 읽지 마세요.

### B. 전체 스택 — 웹 UI + PostgreSQL

```bash
cp .env.example .env                        # 기본값: MOCK_MODE=1, 에이전트 꺼짐
docker compose up -d db                     # pgvector/pgvector:pg16, localhost:5432
export DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit
uv run python db/setup_all.py               # 마이그레이션 15개 · 도메인 · PC 부품 51개 · 리뷰 요약 153건
uv run python scripts/generate_and_seed_baby_catalog.py   # 합성 유아용품 188개 (유아 도메인)
uv run uvicorn src.api:app --reload --host 127.0.0.1 --port 8000
```

<http://127.0.0.1:8000>을 엽니다 — API가 프론트를 같은 오리진에서 서빙하므로 두 번째 서버는 없습니다. Swagger UI는 `/docs`. `GET /health`는 프로세스가 떠 있다는 뜻일 뿐 DB 연결을 보장하지 않습니다. DB 셋업의 표준 문서는 [`db/README.md`](db/README.md)이며 Docker 없이 conda로 하는 방법도 있습니다. 개발자마다 로컬 DB를 쓰고 공용 DB는 없습니다.

### C. 실제 LLM과 에이전트

```ini
MOCK_MODE=0
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=...
CONDITIONS_AGENT=1
RESULT_AGENT=1
```

테스트도 `.env`를 읽습니다 — `MOCK_MODE=1 uv run python -m pytest -q`로 돌리지 않으면 결과 에이전트 테스트가 OpenAI를 호출합니다.

### D. Docker 배포

```bash
docker compose up -d --build                     # db + api (이미지: Dockerfile)
docker compose exec api python db/setup_all.py   # 최초 1회
```

이미지에 `scripts/`가 없으므로 유아 카탈로그 시드는 호스트에서 공개 포트로 실행합니다. `JWT_SECRET`을 바꾸고(`APP_ENV=production`이면 개발 기본값으로 기동을 거부합니다), HTTPS 뒤에서는 `COOKIE_SECURE=1`, UI를 다른 오리진에서 서빙할 때만 `ALLOWED_ORIGINS`를 둡니다 — API는 같은 오리진 전제이며 다른 `Origin`을 단 변경 요청에는 `403`을 냅니다.

## 되는 것과 안 되는 것

| 영역 | 되는 것 | 한계 |
|---|---|---|
| PC 추천(웹) | 게스트 세션 → 조건 → 실행 → 이유·구매 전 확인·리뷰 한 줄·대안·교체·수량/시점·결과 대화 → 확정 → 리포트 → 목표가 추적까지 전부 저장 | 부품 51개 카탈로그의 **합성 가격**. 호환 검사는 근사(소켓·전력·크기). 교체 뒤 검증은 재실행되지 않음(화면의 "다른 구성 보기"가 그 역할) |
| 유아용품 추천(웹) | 조건(월령·필요 영역·건강/피부·보유 품목·체중·혼자 앉기) → 실행 → 품목별 후보와 안전 검사 → 예산 배분 | 함께 들어 있는 합성 카탈로그로는 **게이트를 통과하는 후보가 없음**(부류별 검수된 안전 규칙 없음, 리콜 표지). 그래서 실행은 *done*이지만 선택 0건에 "예산 안에서 채울 수 없는 필수 품목이 있어요"로 끝남 — 기제는 돌고, 데이터가 아직 고르게 해 주지 않음 |
| 대화 | 칩 + 자유 입력. Strands 조건 에이전트(opt-in)는 키워드 규칙이 놓치는 "추가 조건·변경 요청"을 반영. 영어 세션은 전부 영어 | 규칙 경로는 정해진 키워드만 앎. 에이전트는 OpenAI 키 필요 |
| 인증·리스트 | 이메일+비밀번호(argon2), httpOnly JWT 쿠키, 게스트 → 계정 병합, 이름 변경·삭제, 소프트 탈퇴 | 이메일 인증과 비밀번호 재설정 메일은 10/26로 미룸. `/auth/request-code`, `/auth/verify`는 스텁(`501`) |
| 리뷰 근거 | 데모 부품 51개 중 25개의 관계·행동 축 관측 사실이 [3-B] 순위(강등만, 제외 없음)·[5] 설명·`GET /reviews/summary`에 연결 | 조작 라벨이 없어 **탐지율도 정제 평점도 없음**(`cleaned_rating`은 항상 null — [결정 0001](docs/decisions/0001-정제-후-평점을-판정기-없이-내지-않는다.md)). 리뷰 **작성**은 데모 범위 밖 |
| RAG | *구매 전 확인*이 합성 부품 사용 가이드 18건을 인메모리 임베딩으로 인용. 유아 설명서는 local-file 검색 제공자(`BABY_SEARCH_PROVIDER=local-file`, 청크 5개, 회귀 질의 21/21)에 게시되고 검수된 문장에서만 좌석 조건을 검증 | PostgreSQL `rag` 스키마는 멘토 검토 뒤 삭제(마이그레이션 0011) — 청크·벡터는 RDB에 두지 않는다. 호스팅 벡터 저장소는 계획만 있고 미설정. 제공자가 없으면 적합성은 *unknown*이지 조용한 대체가 아님 |
| 데이터베이스 | 58 → 38 축소 후 스키마 10개 / 테이블 38개, FK·UNIQUE·CHECK, `updated_at` 트리거, 원샷 `db/setup_all.py`, RDS 호환 SQL | 낙관적 잠금·상태 전이·스키마 간 불변성은 DB가 아니라 서비스가 강제 |
| 데이터 도구 | Amazon Reviews'23 배치, 합성 카탈로그·설명서, 스펙 수집기 | 실시간 가격·스펙 연동 없음. 알림·피드백 학습 워커는 스텁 |

## API

OpenAPI 문서(`/docs`)에 작업 38개. 쿠키 인증: 익명 세션은 `truefit_guest`, 로그인 뒤는 `truefit_session`(JWT).

| 그룹 | 작업 | 상태 |
|---|---|---|
| `/session` (14) | `POST /session`, `GET /session/{id}`, `POST …/category`, `PATCH …/slot`, `POST …/message`, `…/answer`, `…/reset`, `…/spec-file`, `POST …/recommend` (202), `GET …/result`, `PATCH …/items/{item_id}`, `GET …/items/{item_id}/alternatives`, `POST …/items/{item_id}/swap`, `POST …/result-message` | 동작, 로그인 불필요 |
| `/lists` (6) | `GET /lists`, `PATCH /lists/{id}`, `DELETE /lists/{id}`, `POST …/confirm` (`If-Match` 잠금 버전), `GET …/report`, `POST …/alert` | 동작. 확정·리포트·알림은 로그인 필요 |
| `/auth` (10) | `signup`, `login`, `logout`, `GET/PATCH me`, `password`, `withdraw`, `email-availability` | 동작. `request-code`, `verify` → `501`(이메일 인증용으로 보류) |
| `/reviews` (5) | `GET /reviews/summary/{product_key}` (엔진 키·요약 키·ASIN 모두 받음) | 동작. `pending` / `part` / `publish`는 DB의 리뷰 초안을 읽고 씀. `build` → `501`. 리뷰 작성은 데모 범위 밖 |
| `/dev` (2) | `GET /dev/scenarios`, `POST /dev/run` | DB 없는 시나리오 파이프라인. 공개 전에 제거하거나 막을 것 |
| `/health` | `GET /health` | 프로세스 생존만 |

오류 봉투는 하나입니다: `{"error": {"code", "message", "field"}}`. 프론트가 기준으로 삼는 계약은 [`docs/frontend_외부수정요청.md`](docs/frontend_외부수정요청.md).

## 리뷰 근거 — 관계·행동 축

본문을 읽지 않고 **누가·무엇을·언제** 리뷰했는지를 보고, 누구나 확인·반박할 수 있는 상품 단위 관측을 만듭니다. 7일 안에 몰린 리뷰 비율, 다른 상품과 공유하는 리뷰어, 계정 구성 — 각각 같은 상품 부류의 중앙값을 대조군으로 둡니다. 원천: Amazon Reviews'23 (Electronics: 4,390만 건, ≈12 GB, ≈6분). 원본 `.jsonl`은 저장소에 없고 `data/amazon23/`은 `.gitignore`입니다.

```bash
uv sync --group review-analysis --group test          # pandas · numpy · scipy · httpx
uv run python scripts/amazon23_edges.py <Electronics.jsonl> --cat electronics      # 리뷰 → 엣지 표 (원문 버림)
uv run python scripts/amazon23_meta_slim.py <meta_Electronics.jsonl> --cat electronics
uv run python scripts/map_parts_to_asin.py            # data/parts_list.csv ↔ ASIN (25/51 — 나머지는 2023-09 이후 출시)
uv run python -m src.workers.review_cleanse_worker data/amazon23/electronics_edges.tsv \
    --meta data/amazon23/electronics_meta.tsv --category "Computer Components|Data Storage" \
    --out data/amazon23/pcparts_product_risk.json
uv run python -m src.workers.review_cleanse_worker --lookup amd-ryzen-5-5600   # 부품 하나의 카드
```

- 산출 JSON이 없으면 `ProductRiskStore`는 `None`이고 모든 소비처가 *관측 없음*을 보입니다 — 값을 지어내지 않습니다.
- `GET /reviews/summary`는 관측 블록과, 따로, `is_synthetic: true` 표지가 붙은 합성 데모 블록을 돌려줍니다. 화면은 그 표지를 유지해야 합니다.
- 앞으로의 수집기가 첫날부터 잡아야 할 것(작성자 해시·게시 시각·옵션 단위 대상)은 [`docs/review_collector.md`](docs/review_collector.md), 저장 컬럼은 [결정 0002](docs/decisions/0002-review_summary에-작성자-해시와-게시시각을-둔다.md). 빠지면 소급이 안 됩니다.

## 데이터와 도구

| 도구 | 용도 |
|---|---|
| `db/setup_all.py` | 마이그레이션 + 기준 데이터 + PC 카탈로그 + 리뷰 요약, 멱등 |
| `scripts/generate_and_seed_baby_catalog.py` | 결정적 합성 유아용품 카탈로그(상품 188개, 품목 유형 18개) → DB upsert. `--dry-run`은 DB 없이 검증만 |
| `scripts/generate_baby_manual.py` | JSON 사양(`data/synthetic_manuals/stroller_example.json`)에서 규칙 기반 **부분** 설명서 생성 — 사실 원장·인용·해시·검증 포함, 조작법·안전 지침은 지어내지 않음. [상세](docs/synthetic_manual_generator.md) |
| `scripts/rag_manual.py ingest\|query\|evaluate --provider local-file` | 생성한 설명서를 local-file 검색 제공자(`.baby-search-index/`)에 게시·질의·21건 회귀. `BABY_SEARCH_PROVIDER=local-file`이면 API도 같은 인덱스를 씀. 비우면 *미설정* |
| `scripts/build_specs.py` | CPU/GPU/메인보드 1차 출처 스펙 수집기, 출처 URL 저장(1건/초, robots.txt, 캐시). 대상 사이트 대부분이 클라이언트 렌더라 수동 목록이 남음. [설명](scripts/README.md) |
| `scripts/gen_review_summaries.py` | 데모용 합성 리뷰 요약(`data/review_summaries.json`) — 실제 리뷰 아님 |
| `scripts/import_review_analysis.py` · `evaluate_review_signals.py` | 파일 기반 리뷰 분석 결과를 `evidence.*`에 적재. 누수 분할을 거부하는 연구용 평가 |
| `scripts/check_baby_readiness.py` | 유아 DB 준비 상태의 읽기 전용 보고(JSON, 접속 문자열 미포함) |

저장소에 실제로 있는 데이터: `data/parts_list.csv`(51개), `data/parts_asin_map.csv`, `data/parts_specs*.{csv,json}`, `data/pc_care_guides.json`, `data/review_summaries.json`(합성), `data/review_suspect_counts.json`, `data/baby/catalog_demo_v1.json`, 시나리오 2개, 설명서 입력 1개.

## 저장소 구성

```text
main.py                       콘솔 파이프라인 진입점 (시나리오 파일, 목 LLM)
src/
  api.py, routers/, schemas.py FastAPI 앱, 라우터 5개, API 계약. frontend/ 서빙
  services/                   session · recommendation · list · auth · review · feedback
  agent/                      Strands 에이전트: conditions_agent.py, result_agent.py
  engine/                     단계 [1]~[6] (+ slot_rules 키워드 추출, prompts, lang)
  pipeline.py                 콘솔용 단계 오케스트레이션
  rag/                        care_guides(인메모리 RAG) · provider(외부 검색 경계) ·
                              ingestion · evidence_search · verification · contracts
  repo/                       SQL 저장소 (plan, engine, product, user, review, rag, …)
  workers/                    review_cleanse_worker + relation_axis (배치). 나머지 워커는 스텁
  auth/, db/, config.py       JWT/argon2/Origin 검사 · psycopg 풀 · env 설정
config/categories/            computer.yaml · baby.yaml (슬롯·질문·모드) + 유아 규칙
frontend/                     페이지 10개, css/, js/ (api.js · core.js · planner-shell.js · i18n.js · pages/)
db/                           migrate.py · 마이그레이션 15개 · seed*.py · setup_all.py · README.md
scripts/                      카탈로그·설명서 생성기 · RAG CLI · Amazon'23 배치 · 스펙 수집기
data/                         부품 목록, 스펙, 사용 가이드, 시나리오, 합성 입력
docs/                         DB 명세·구조도, API 계약, 에이전트 문서, decisions/, 회의 기반 보고서
generated/                    설명서 예시, RAG 평가 산출물
tests/                        파이프라인 · 에이전트 · HTTP 흐름 · 서비스 · SQL/마이그레이션 검사
Dockerfile, docker-compose.yml
```

## 테스트와 확인 범위

```bash
MOCK_MODE=1 uv run python -m pytest -q                       # DATABASE_URL 없으면 DB 테스트는 건너뜀
DATABASE_URL=postgresql://…/<일회용> MOCK_MODE=1 uv run python -m pytest -q   # setup_all + 유아 시드 뒤
```

이 README를 위해 2026-09-14에 실측한 결과:

| 실행 | 결과 |
|---|---|
| DB 없음 | **264 passed, 162 skipped, 1 failed**, 1초 미만. 실패 1건은 마이그레이션 목록을 옛 `develop` 커밋에 고정한 테스트가 `0014_candidate_checks.sql`을 drift로 보는 것 — 낡은 건 테스트지 스키마가 아님 |
| 새 DB(`setup_all.py` + 유아 시드), 목 LLM | **402 passed, 17 failed, 8 skipped**, 8초. 실패: 병합 전 결과 형태(품목별 `status`)를 전제한 유아 트랙 HTTP 테스트 6건, 아직 충족 못 한 인증 강화 수용 테스트 7건(`email-availability` 속도 제한, 잠금 카운터 초기화, 비밀번호 변경 직후 JWT 무효화, 탈퇴 시 동의 시각 삭제), 이중 확정/잠금 버전 충돌 2건, 요구사양 형태 1건, 위의 낡은 마이그레이션 고정 1건. 건너뜀: pandas 미설치(2), 전용 일회용 DB를 요구하는 테스트(6) |
| 콘솔 | `computer_pass`, `computer_research` 종료. 결과표 + 리뷰 관측 줄 |
| HTTP, PC 도메인 | 세션 → 자유 텍스트 조건("게임용으로 200만원, 조용했으면") → 추천 → `done`, 8개 품목, 2,000,000원 중 1,439,000원, 신뢰도 94, 구매 전 확인·리뷰 줄 있음 → 결과 대화로 CPU 교체 → 대안 목록 → 매핑 안 된 부품의 리뷰 요약은 *unavailable*로 정직하게 반환 |
| HTTP, 유아 도메인 | 필요 영역 세 가지(외출·수유·수면) 모두 `done`. 후보 19~26개가 검사 문장과 함께 나열되고 선택은 0건(한계 참고) |
| RAG | `rag_manual.py ingest/query/evaluate --provider local-file`: 청크 5개, `verification_status: partial`의 발췌 답변, 21/21 |

미확인: 여러 세션에 걸친 실제 LLM 출력 품질, 운영 PostgreSQL 부하, 실제 제품 안전성·가격·호환성, AWS 위의 Docker 이미지.

## 남은 것과 다음 단계

1. **자기 게이트를 통과하는 유아 카탈로그** — 부류별 검수된 안전 규칙과 합성 상품의 인증·리콜 데이터. 그래야 배분 단계가 고를 게 생김.
2. `src/rag/provider.py` 뒤의 **호스팅 벡터 검색**(경계와 local-file 구현은 있음). 그다음 설명서 근거를 PC 검사에도 연결.
3. 테스트가 이미 적어 둔 인증 강화: 속도 제한, 잠금 카운터 의미, 즉시 JWT 무효화, 탈퇴 시 완전 익명화. 이메일 인증·비밀번호 재설정(10/26로 미룸).
4. 교체 뒤 재검증. 실제 스펙·가격 연동과 정확한 호환 규칙. 지금의 근사를 넘는 PC 하드필터.
5. 리뷰: 첫 레코드부터 작성자 해시·게시 시각·옵션 단위 대상을 잡는 수집기. 사람 라벨링 규약(검토 큐 유입 경로와 무작위 대조 표본 비율을 첫 라벨 **전에** 확정). 그다음에야 정제 평점.
6. 가격 추적·알림·피드백 학습 — 워커는 스텁으로만 있음. 배치 학습은 보류.

## 라이선스와 문서

MIT — [`LICENSE`](LICENSE).

- [`db/README.md`](db/README.md) — DB 셋업(표준), 마이그레이션 목록, AWS/RDS 호환 원칙
- [`docs/db/table_spec.md`](docs/db/table_spec.md) — 테이블 명세. [구조도](docs/db/database-structure-overview.png) · [SVG](docs/db/database-structure-overview.svg) · [축소 제안](docs/db/db_schema_reduction_proposal_2026-09-12.md)
- [`docs/frontend_외부수정요청.md`](docs/frontend_외부수정요청.md) — 프론트 ↔ 백엔드 API 계약. [`frontend/CLAUDE.md`](frontend/CLAUDE.md) — 화면 지도와 프론트 규칙
- [`docs/decisions/`](docs/decisions/README.md) — 되돌리기 어려운 결정과 시도했다가 안 통한 대안
- [`docs/review_analysis_contract.md`](docs/review_analysis_contract.md) · [`docs/review_collector.md`](docs/review_collector.md) · [`docs/review_module_handoff.md`](docs/review_module_handoff.md) — 리뷰 분석 파일 계약, 수집기 요구, 모듈 인계
- [`docs/agent-tasks/baby/`](docs/agent-tasks/baby/README.md) — 유아 도메인 작업 P0~P9와 수용 보고서
- [`docs/synthetic_manual_generator.md`](docs/synthetic_manual_generator.md) — 설명서 생성기 입력 계약. [`docs/rag_implementation.md`](docs/rag_implementation.md)는 **삭제된** pgvector 설계를 적은 것으로 기록용으로만 남김
