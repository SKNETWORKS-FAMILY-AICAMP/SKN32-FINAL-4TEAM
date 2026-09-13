# TrueFit — 목적성 쇼핑 플래너

사용자의 목적·예산·조건에 맞춰 필요한 물품을 구성하고, 선택 근거와 외부 구매 링크를 제공하는 프로젝트입니다. 설계 범위는 **PC 본체 조립과 유아용품 준비**이며 요리 도메인은 제외합니다.

**현재는 PC 추천 시나리오 데모, 가상 설명서 생성기, 설명서 RAG, 화면 목업을 개발한 단계입니다.** 일반 사용자 API·인증·계획 저장·알림까지 연결된 서비스는 아직 아닙니다. 아래는 2026-09-11
저장소의 코드와 산출물 기준입니다.

![](docs/service-flow/슬라이드1.PNG)
![](docs/service-flow/슬라이드2.PNG)
![](docs/service-flow/슬라이드3.PNG)

## 개발 현황

| 영역             | 구현된 내용                                                                                          | 현재 한계                                                                               |
|------------------|------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| PC 추천 데모     | 조건 정리 → 요구사양 → 후보 → 필터·순위 → 구성 → 검증·재탐색 → 설명의 콘솔 실행                      | LLM·가격·성능값·검증 점수에 목(mock) 데이터 사용. 실제 호환성·예산 준수 보장 없음       |
| 화면             | `frontend/`의 멀티페이지 화면(랜딩·카테고리·조건 대화·추천 결과·확정·리포트·로그인·회원가입·회원정보), 장바구니 전환·이름 변경·삭제 | 실제 API(`TF_API`)를 호출하도록 연결되어 있으나 백엔드 대부분이 501이라 실제로는 미동작    |
| API              | FastAPI 앱, 요청·응답 모델, 공통 오류 처리, 상태 확인·개발용 시나리오 API                            | 일반 사용자용 20개 작업은 미구현이며 호출 시 501 등 오류 반환                           |
| 데이터베이스     | 12개 스키마·58개 업무 테이블의 DDL, FK·UNIQUE·CHECK·인덱스·갱신 시각 트리거, 활성 임베딩 프로필 제약 | 공통 연결 풀과 대부분의 repo 미구현. 전체 업무 무결성·권한·상태 전이 구현은 남아 있음   |
| 설명서 생성      | 유모차·젖병·기저귀·컵의 규칙 기반 부분 설명서, 사실 원장·인용 위치·해시·검증 파일                    | 모든 출력은 `partial`. 입력에 없는 조작법과 전체 안전 지침을 생성하지 않음              |
| 설명서 RAG       | Markdown 청크화, DB 적재·게시, pgvector+키워드 검색, 검색·인용 기록, 권한·철회 검사                  | 관리자 CLI 중심. 단일 가상 유모차 자료로 회귀 평가. PDF/OCR·S3·전체 추천 UI 연결 미구현 |
| 임베딩           | Bedrock Titan v2 어댑터와 명시적 `local-test` 1024차원 벡터                                          | Bedrock 실모델 품질 평가는 미수행. local-test는 어휘 해시 벡터                          |
| 리뷰·데이터 도구 | PC 합성 리뷰 요약 생성, 공식 스펙 수집 스크립트, 유아용품 상품 생성 코드                             | 운영 리뷰 작성·집계·학습 파이프라인 미구현. 상품 생성 기본 사전 파일 누락               |
| 리뷰 관계·행동 축 | 공개 리뷰 데이터(Amazon Reviews'23)에서 리뷰어–상품 그래프의 **관측 사실**(7일 몰림·공유 리뷰어·계정 구성)을 배치로 산출하고 데모 부품 25종에 연결. 계약 리더(`ProductRiskStore`)까지 | 조작 라벨이 없어 탐지율·정제 후 평점은 산출하지 않음(`cleaned_rating`은 null). `GET /reviews/summary`·[3-B] 리뷰축·[5] 설명에 연결됨. 수집기·`author_ref` 저장은 미구현 |

## 빠른 시작

프로젝트 루트에서 실행합니다. Python **3.11**과 `uv`를 사용합니다. DB 없이 PC 콘솔 데모와 기본 테스트를 실행할 수 있습니다.

```powershell
uv sync --locked
uv run python main.py --list
uv run python main.py computer_pass
uv run python main.py computer_research
uv run python -m pytest -q
```

- `computer_pass`: 8개 PC 슬롯을 구성하고 1회 검증으로 통과하는 목 시나리오입니다.
- `computer_research`: 주입된 점수 72 → 후보 교체·재탐색 → 86 흐름을 보여줍니다.
- `stage4_optimize.py`는 현재 슬롯별 후보를 고르는 근사 구현입니다. 로그의 조합 수는 실제 완전탐색 수행량이 아니며, 재탐색 후 예산을 초과할 수 있습니다.
- 검증 점수·고정 기여도·합성 가격을 실제 상품의 품질·시세·호환성 평가로 해석하지 않습니다.

설정은 **프로세스 환경변수**로 전달합니다. [`.env.example`](.env.example)은 설정 항목 참고용이며 현재 코드가 `.env` 파일을 자동으로 읽지는 않습니다. PC 데모는 기본
`MOCK_MODE=1`로 동작합니다. 설명서 RAG CLI의 `--provider`는 이 값과 별개입니다.

### API 실행

```powershell
uv run uvicorn src.api:app --reload --host 127.0.0.1 --port 8000
```

- API 문서: [Swagger UI](http://127.0.0.1:8000/docs)
- 상태 확인: [GET /health](http://127.0.0.1:8000/health)

```powershell
Invoke-RestMethod http://127.0.0.1:8000/dev/scenarios
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/dev/run -ContentType 'application/json' -Body '{"scenario":"computer_pass"}'
```

`/dev/*`는 DB를 사용하지 않는 개발용 목 실행 경로입니다. `/health`의 성공은 DB 연결이나 전체 서비스 준비 완료를 뜻하지 않습니다. 현재 앱에는 개발 라우터가 포함되어 있으므로 배포 전에 노출
정책을 적용해야 합니다.

### 화면 목업 보기

API와 별도 터미널에서 정적 파일 서버를 실행합니다.

```powershell
uv run python -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

[TrueFit 랜딩](http://127.0.0.1:5500/index.html)을 엽니다. 페이지마다 파일이 나뉜 멀티페이지 구조이며(화면 지도는 `frontend/CLAUDE.md` 참고), 모든 화면이 `TF_API`로 실제 백엔드를 호출합니다. 지금 열어 둔 장바구니 ID만 브라우저 `localStorage`에 남고, 나머지 데이터는 API·서버 계정을 거칩니다. 백엔드 대부분이 아직 501이라 API와 같은 도메인에서 서빙하거나 CORS를 열어야 화면이 정상 동작하며, 구체적인 요청 사항은 `docs/frontend_외부수정요청.md`에 정리되어 있습니다.

## 데이터베이스와 구조 문서

PostgreSQL과 pgvector를 같은 DB에서 사용합니다. 설계상 파일 원본은 별도 객체 저장소에 두며, 현재 설명서 RAG는 관리자용 로컬 `.rag-files/`를 사용합니다.

![데이터베이스 → 스키마 → 테이블 구조도](docs/db/database-structure-overview.png)

- [테이블 명세서 v4](docs/db/table_spec.md): 설계 기준, 58개 테이블·컬럼·제약·수용 기준
- [데이터 구조 설계 근거](데이터_구조_설계_근거.md): 업무별 분리 이유, 초기 범위, 리뷰·학습 데이터 정책
- [개발 역할 분담](개발_역할_분담.md): 5인 소유 영역, 통합 순서, 충돌 방지 규칙과 가격 알림 제외 범위
- [확대 가능한 SVG](docs/db/database-structure-overview.svg)
- [항목을 편집할 수 있는 PPTX](docs/db/pptx/database-structure-overview.pptx): 가로형 1장, 텍스트·도형·선 개별 편집
- [DB 마이그레이션 설명](db/README.md)

### 로컬 DB 준비

Docker를 사용할 수 있는 환경에서 실행합니다.

```powershell
docker compose up -d db
$env:DATABASE_URL='postgresql://truefit:truefit@localhost:5432/truefit'
uv run python db/migrate.py up
uv run python db/migrate.py status
```

컨테이너는 `pgvector/pgvector:pg16`을 사용합니다. DB가 연결 가능한 상태가 된 뒤 마이그레이션을 적용합니다.

| 마이그레이션                  | 내용                                   |
|-------------------------------|----------------------------------------|
| `0000_prereq.sql`             | vector 확장·12개 스키마·갱신 시각 함수 |
| `0001_tables.sql`             | 58개 업무 테이블·PK·CHECK·기본값       |
| `0002_unique.sql`             | 단순·복합·부분·표현식 UNIQUE           |
| `0003_foreign_keys.sql`       | 스키마 간 FK와 소속 일치 복합 FK       |
| `0004_triggers.sql`           | updated_at 갱신 트리거                 |
| `0005_indexes.sql`            | 조회·조인·검색 인덱스                  |
| `0006_rag_active_profile.sql` | 활성 임베딩 프로필 하나만 허용         |

벡터 컬럼은 현재 `vector(1024)`입니다. 명세의 차원 D와 달리 실행 코드에는 초기 차원이 정해져 있으므로 모델·차원 변경 시 재임베딩과 마이그레이션을 검토해야 합니다. DDL 제공이나 RAG 통합 테스트
통과가 모든 업무 규칙 구현을 뜻하지는 않습니다.

## 가상 사용설명서 생성

예제 유모차 입력에서 별도의 새 출력 폴더로 부분 설명서를 생성합니다. API 키·LLM 호출은 필요 없습니다.

```powershell
uv run python scripts/generate_baby_manual.py --input data/synthetic_manuals/stroller_example.json --output generated/synthetic_manuals/stroller_readme_run
```

출력 폴더가 이미 있으면 덮어쓰기를 거절합니다. 재실행할 때 새 경로를 지정합니다. 저장소에는 `generated/synthetic_manuals/stroller_example/` 예시가 이미 있습니다.

출력은 `manual.md`, `facts.jsonl`, `mapping.json`, 상품·참조·프로필 스냅샷, `validation.json`, `manifest.json`입니다. 생성기의 검증 통과는 데이터
일관성 검사이며 실제 제품 안전 인증이나 사람 검수 완료를 뜻하지 않습니다.

[생성기 구현·입력 계약·테스트](docs/synthetic_manual_generator.md)

## 설명서 RAG 실행

마이그레이션을 적용한 개발 DB와 저장소의 설명서 예시를 사용합니다. 다음은 AWS 호출 없는 가상 코퍼스 회귀 실행입니다.

```powershell
$env:DATABASE_URL='postgresql://truefit:truefit@localhost:5432/truefit'
uv run python scripts/rag_manual.py ingest --provider local-test
uv run python scripts/rag_manual.py query --provider local-test --new-test-run --query '바구니 최대 하중은?'
uv run python scripts/rag_manual.py evaluate --provider local-test --new-test-run --report generated/rag/stroller_readme_evaluation.json
```

- `manual.md`만 검색합니다. 사실 원장·상품 스냅샷·평가 정답은 검색·임베딩에서 제외합니다.
- 절 단위 청크와 원문 해시·문자 범위·줄 번호를 보존하고 검색 실행·결과·인용을 DB에 기록합니다.
- 정확 코사인 검색과 한국어 문자 bigram/모델명 키워드를 RRF로 결합합니다.
- 검색과 인용 반환 시 권한·자료 상태·상품/옵션·언어·시장·도메인·모델 프로필을 검사합니다.
- 근거 부족과 오류를 구분하며, 장애 시 목 결과나 local-test로 자동 대체하지 않습니다.
- `--new-test-run`은 가상 평가용 실행 문맥을 만듭니다. 실제 소비처는 권한을 확인한 추천 실행 ID를 전달해야 합니다.
- `--reviewed`는 관리자의 검수 완료 표시입니다. 생성기 검증 결과로 자동 설정하지 않습니다.

Bedrock 경로는 `--provider bedrock`, AWS 자격증명·리전, 기본 `amazon.titan-embed-text-v2:0`을 사용합니다. local-test 모델이 이미 활성인 DB에 다른
모델을 바로 게시할 수 없습니다. 별도 DB 또는 명시적 프로필 전환이 필요합니다. `RAG_TEST_DATABASE_URL`이 설정돼 있으면 CLI는 `DATABASE_URL`보다 그 값을 우선 사용합니다.

[상세 실행법·PGlite 테스트 DB·Bedrock 설정·제한](docs/rag_implementation.md) · [기존 회귀 평가 산출물](generated/rag/README.md)

## 리뷰 관계·행동 축 실행

본문을 보지 않고 **누가·언제** 리뷰했는지로 상품 단위 관측 사실을 만듭니다. 산출물은 점수가 아니라
"리뷰 200건 중 100건(50%)이 7일 안에 몰림 — 부류 중앙값 5.5%" 같은 확인·반박 가능한 문장입니다.
공개 데이터 원본(jsonl)은 저장소에 없고 `data/amazon23/`은 `.gitignore`입니다.

```powershell
uv sync --group review-analysis --group test                     # pandas·numpy·scipy (배치) · httpx (API 테스트)
uv run python scripts/amazon23_edges.py <Electronics.jsonl> --cat electronics       # 리뷰 jsonl → 엣지 표 (원문 버림)
uv run python scripts/amazon23_meta_slim.py <meta_Electronics.jsonl> --cat electronics
uv run python scripts/map_parts_to_asin.py                        # data/parts_list.csv ↔ ASIN (data/parts_asin_map.csv)
uv run python -m src.workers.review_cleanse_worker data/amazon23/electronics_edges.tsv `
    --meta data/amazon23/electronics_meta.tsv --category "Computer Components|Data Storage" `
    --out data/amazon23/pcparts_product_risk.json                 # 43.9M건 ≈ 12GB·6분. 대조군은 같은 부류로
uv run python -m src.workers.review_cleanse_worker --lookup amd-ryzen-5-5600   # 부품 하나의 카드
uv run python main.py computer_pass                               # 결과표 아래 "리뷰 관측" 줄
```

- 산출 JSON(`data/amazon23/pcparts_product_risk.json`, 5MB)이 없는 환경에서는 `ProductRiskStore`가 `None`이고
  호출자는 "관측 없음"으로 다룹니다. 팀원 기계에는 이 파일을 따로 전달해야 합니다
- 정제 후 평점(`cleaned_rating`)은 판정기가 없어 **항상 null**입니다 — [결정 0001](docs/decisions/0001-정제-후-평점을-판정기-없이-내지-않는다.md).
  합성 데모값(`data/review_summaries.json`)은 `is_synthetic: true`와 함께만 나오며 화면은 그 표지를 붙여야 합니다
- 수집 시점에 잡을 것은 [수집기 설계](docs/review_collector.md) — 작성자 해시·게시 시각·옵션 단위 대상. 빠지면 소급이 안 됩니다

## API 계약과 구현 상태

OpenAPI에는 업무·개발용 22개 작업과 `/health` 1개가 등록되어 있습니다. 인증 표시는 구현 목표이며 현재 인증 기능은 미구현입니다.

| 그룹   | 경로                                                                                                                                                       | 현재 상태                          |
|--------|------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------|
| 상태   | `GET /health`                                                                                                                                              | 동작                               |
| 개발   | `GET /dev/scenarios`, `POST /dev/run`                                                                                                                      | 목 시나리오 실행                   |
| 인증   | `POST /auth/request-code`, `/auth/verify`, `/auth/logout`, `GET /auth/me`                                                                                  | 이메일 코드·JWT·세션 병합 미구현   |
| 세션   | `POST /session`, `POST /session/{list_id}/category`, `/message`, `/answer`, `/recommend`, `PATCH /session/{list_id}/slot`, `GET /session/{list_id}/result` | 계약·진입점 중심, 서비스 구현 필요 |
| 리스트 | `POST /lists/{list_id}/confirm`, `GET /lists/{list_id}/report`, `GET /lists`                                                                               | 확정·저장·리포트 미구현            |
| 리뷰   | `GET /reviews/pending`, `POST /reviews/part`, `/reviews/build`, `/reviews/{review_id}/publish`                                                            | 작성·게시·운영 집계 미구현. 작성 요청의 `telemetry`(폼 계측값, 횟수·시간만) 계약은 확정 |
| 리뷰 요약 | `GET /reviews/summary/{product_key}`                                                                                                                    | 동작 — 관계 축 관측 + 합성 데모 블록(표지 포함). 인증 없음 |

설명서 RAG는 CLI·서비스 함수로 구현되어 있으며 별도 HTTP 엔드포인트를 제공하지 않습니다. 공통 `src/db` 연결 풀은 미구현이지만 RAG CLI·검색 함수는 psycopg 직접 연결과 `RagRepo`
를 사용합니다.

## 데이터 준비 도구

| 도구                                | 용도와 실행 조건                                                                                                                                                                              |
|-------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `scripts/build_specs.py`            | PC 공식 스펙 수집, 출처·실패 목록 저장. `requests`, `beautifulsoup4`, `lxml` 추가 설치 필요. 코드에는 Chrome/Edge를 이용한 `--render` 재시도 경로도 있음. 추출되지 않은 규격은 수동 확인 필요 |
| `scripts/gen_review_summaries.py`   | `data/parts_list.csv`에서 데모용 합성 리뷰 요약·평점 생성. 실행하면 기존 출력 파일을 다시 작성함. 운영 후기나 실제 조작 판정 데이터가 아님                                                    |
| `scripts/amazon23_edges.py` · `amazon23_meta_slim.py` · `map_parts_to_asin.py` | Amazon Reviews'23 리뷰 jsonl → 엣지 표(원문 버림), 메타 → 제목·카테고리 TSV, 데모 부품 ↔ ASIN(부품별 손 규칙, 25/51 — 나머지는 2023-09 이후 출시). 원본은 별도 수령 |
| `scripts/generate_baby_products.py` | 23개 유아용품 품목군의 가상 상품 생성 코드. 기본 입력인 `scripts/유아용품_가상제품_스펙사전_v1.json`은 현재 저장소에 없어 기본 실행 불가. 호환 사전을 `--dictionary`로 제공해야 함            |

[스펙 수집기 설명](scripts/README.md)과 [상품 생성기 기존 사용법](가상제품_생성기_사용법.md)은 참고 문서입니다. 기존 문서의 일부 경로·`--render` 구현 상태·상품 생성 테스트/사전
목록은 현재 배치와 다르므로 코드 및 위 표를 함께 확인합니다. 부분 설명서 생성은 별도 예제 입력을 사용하므로 누락된 상품 사전 없이 실행할 수 있습니다.

## 저장소 구성

```text
main.py                        PC 콘솔 데모 진입점
src/
  api.py, routers/, schemas.py  FastAPI 라우트와 API 계약
  pipeline.py, engine/         추천 단계·재탐색·설명, 일부 목/근사
  rag/                        설명서 청크화·임베딩·검색·검증·설명
  repo/rag_repo.py             RAG SQL 적재·게시·검색·인용
  repo/catalog_repo.py         CSV 기반 PC 데모 후보
  repo/                       그 외 업무 저장소는 대부분 미구현
  db/, auth/, services/        공통 연결·인증·업무 서비스 뼈대
  workers/                    추출·리뷰·가격·알림·학습 작업 진입점
  workers/relation_axis.py    리뷰어–상품 그래프 관측 사실·근거 카드 (review_cleanse_worker 가 호출)
config/categories/            computer 정의, baby 추천 정의 stub
frontend/                     멀티페이지 화면(*.html) + css/js, 화면 지도는 frontend/CLAUDE.md
scripts/                      스펙 수집·합성 데이터·설명서·RAG CLI
data/                        PC 부품·리뷰 예시·시나리오·설명서 입력
docs/decisions/              되돌리기 어려운 결정과 대가 · docs/review_collector.md 수집 시점 목록
generated/                   설명서 예시·RAG 평가 산출물
db/                          마이그레이션 러너와 SQL
docs/                        RAG·설명서 생성·DB 명세와 구조도
tests/                       파이프라인·설명서·RAG·SQL 통합 테스트
```

## 테스트와 확인 범위

```powershell
# DB 없이 실행. DB 통합 테스트는 환경변수 미설정 시 건너뜀
uv run python -m pytest -q

# 별도 임시 테스트 DB를 준비하고 마이그레이션한 경우
$env:RAG_TEST_DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:55432/postgres?sslmode=disable'
uv run python -m pytest -q tests/test_rag_postgres.py
```

두 번째 명령은 전용 테스트 DB가 필요합니다. Docker 없는 환경의 PGlite 서버 실행·마이그레이션 순서는 [RAG 문서](docs/rag_implementation.md)를 따릅니다.

| 확인 구분                       | 결과                                                                                                          |
|---------------------------------|---------------------------------------------------------------------------------------------------------------|
| 이번 README 갱신 시 기본 테스트 | 31 passed, 27 skipped, 3 subtests passed. DB 통합 환경변수 미설정으로 27건 건너뜀                             |
| 이번 PC 콘솔 확인               | `computer_pass`, `computer_research` 모두 종료 성공                                                           |
| 기존 저장된 RAG 통합 결과       | PGlite/pgvector에서 58 passed, 3 subtests passed, 설명서 질의 21/21. 이번 갱신에서 DB 통합 재실행은 하지 않음 |
| 미확인 영역                     | Bedrock 실모델 검색 품질, 운영 PostgreSQL 부하·동시성, 실제 제품 안전성, 브라우저와 백엔드 전체 연결          |

기본 테스트 실행에는 pytest 캐시 디렉터리 쓰기 권한 경고 1건이 있었으며 테스트 자체는 통과했습니다. 기존 결과 파일은 [generated/rag](generated/rag/README.md)에서 확인할 수
있습니다.

## 다음 구현 과제

1. 공통 DB 연결 풀과 계획·사용자·상품 등 저장소 구현, 명세의 교차 무결성·불변성·동시 수정 검사 적용
2. 이메일 코드·JWT·소유권 확인, 일반 사용자 API와 화면 목업 연결
3. 실제 상품 규격·가격 연동, PC 하드필터·호환 검사·예산 준수 최적화 구현
4. 설명서 RAG의 실제 Bedrock 평가, PDF/OCR·이미지·객체 저장소·비동기 처리 확장
5. 유아용품 사전 복원·입력 검증, `baby.yaml`과 품목별 추천·예산 분기 구현
6. 실제 PC 리뷰·운영 집계, 단일 부모 리뷰 증강·라벨 검수·내보내기 구현. 사람 라벨링을 시작하기 전에 검토 큐 유입 경로와 무작위 대조 표본 비율을 정한다 — 첫 라벨 뒤에는 소급이 안 됨.
   외부 리뷰 수집기는 [수집 시점에 잡을 것](docs/review_collector.md)대로 작성자 해시·게시 시각·옵션 단위 대상을 처음부터 잡는다
7. 가격 추적·알림·사용자 행동 기록 구현. 자동 학습 배치는 현재 명세에서 보류

[프로젝트 기획서](프로젝트_기획서_v2.md) · [기술 기획서](기술기획서_데모+최종.md)
