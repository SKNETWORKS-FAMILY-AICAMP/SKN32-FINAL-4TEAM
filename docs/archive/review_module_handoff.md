# 리뷰 관계·행동 축 — 인수인계 (모듈 / 연결)

**이 문서가 답하는 질문: 리뷰 클렌징 자리에 무엇을 끼우고, 그중 누가 어느 조각을 반영하는가.**
기준일 2026-09-12. `개발_역할_분담.md` 의 충돌 방지 규칙에 맞춰 두 브랜치로 갈랐다.

| 브랜치 | 내용 | 규칙상 자리 |
| --- | --- | --- |
| `feat/review-module` | 배치(`relation_axis` · `review_cleanse_worker`) · 계약 리더(`ProductRiskStore`) · 스크립트 · 데모 매핑 · 결정 기록 · 테스트 | **담당 5** — 그대로 PR |
| `feat/review-wiring` (위에 쌓임) | 아래 조각 여섯 | 담당 2·3 — 통째로 받거나 조각으로 |

## 연결 조각 — 누가 반영하나

| # | 파일 | 무엇 | 누구 |
| --- | --- | --- | --- |
| 1 | `src/schemas.py` | `ReviewTelemetry`(폼 계측값, 횟수·시간만 · `extra="forbid"`) · `ProductRiskOut` · `SyntheticDemoOut` · `ReviewSummaryOut`. develop 의 `Field(default_factory=dict)` 관행에 맞췄다 | 담당 2 (공통 DTO) |
| 2 | `src/services/review_service.py` · `src/routers/reviews.py` | `GET /reviews/summary/{product_key}` — **프론트 계약(`docs/frontend_외부수정요청.md` §D-4-2 `ReviewSummary`) 이름을 따른다.** 낼 수 있는 것(`total_count` · `rating_raw` · `summaries` · `data_notice`)은 채우고 못 내는 것은 **이름을 바꾸지 않고 null**. 실측 블록과 합성 데모 블록(`is_synthetic: true`)은 분리. 산출 JSON 없는 환경은 데모만 | 담당 2 (리뷰 서비스 조립) |
| 3 | `src/engine/stage3b_rank.py` · `config.REVIEW_AXIS_EXCESS` | 리뷰축 0.5 stub → 관측 없음 0.5 · 관측됨 0.75 · **대조군 중앙값 2배 초과 지표 있음 0.25**. 넘은 지표는 `REVIEW_OBS:` 플래그. 규칙에 드는 지표는 `burst7` · `prolific_rate` 둘뿐(1건 계정 비율은 실측 라벨에서 방향이 반대라 뺐다). 출시 첫 주 몰림은 안 센다 | **담당 3** — 순위 규칙은 담당 5 가 직접 바꾸지 않는다. 이 값은 제안이고 반영·조정은 담당 3 |
| 4 | `src/engine/stage5_explain.py` · `src/pipeline.py`(1줄) · `main.py` | 슬롯별 한 줄("리뷰 49건 관측 — 7일 몰림 18.4% (부류 중앙값 5.5%) — 검토 권장") + 주의 문구("상품 단위 신호이며 개별 리뷰의 진위가 아닙니다") | 담당 2 (조립) |
| 5 | `db/migrations/0010_review_summary_relation_axis.sql` | `evidence.review_summary` 에 NULL 허용 `author_ref`(소스별 솔트 해시) · `review_posted_at` + 인덱스 둘. `collected_at` 으로 채우지 않는다 | **담당 2** — 아래 마이그레이션 메모 |
| 6 | `src/services/recommendation_service.py`(DB 추천 경로) | **`stage5_explain.run(..., rank=rank)`** — 빼면 리뷰 관측이 전 슬롯 "없음" 이 된다(기본값이 `None` 이라 조용히). 그리고 `explanation.review_line_by_slot` · `caveats` · 슬롯별 `evidence` 를 `reasoning_log` · `explanation_text` 에 싣는다 | 담당 2 (조립) |
| 7 | `tests/test_review_summary_api.py` · `test_review_telemetry.py` · `test_stage5_review_line.py` · `test_rank_review_axis.py` · `test_review_trace.py` · `test_risk_store_states.py` | 각 조각의 테스트. httpx 없으면 API 테스트만 skip | 조각과 함께 |

## 마이그레이션 메모 — 별도 파일보다 축소 마이그레이션에 포함을 권한다

DB 스키마 축소(58 → 35)가 진행 중이면 이 두 컬럼은 **그 마이그레이션 안에** 넣는 편이 낫다 — 번호 충돌이
없고, `evidence` 재작성 뒤에 ALTER 가 오는 순서가 보장된다. 그 경우 `0010_*.sql` 파일은 버리고 SQL 만 옮긴다.
축소안에서 `review_summary` 는 유지·병합 금지로 확정돼 있어 컬럼의 집은 살아 있다.

`engine.recommendation_candidate.evidence_refs jsonb` 로 가면 `REVIEW_OBS:` 플래그도 그 배열의 항목 하나로
들어가면 된다 — `{"axis": "review", "key": "burst7", "value": 0.184, "control": 0.055}` 모양.

## 산출물 — 코드만으로는 안 돈다

`data/amazon23/pcparts_product_risk.json`(5MB)이 있어야 실측 블록이 나온다. `.gitignore` 라 **따로 전달**한다.
없으면 `ProductRiskStore` 가 `None` 이고 API 는 합성 데모 블록만, 랭킹 리뷰축은 0.5 다. 만드는 법은 README
"리뷰 관계·행동 축 실행"(Electronics 43.9M건 ≈ 12GB · 6분).

**산출물 유무로 추천 결과가 달라진다.** 리뷰축이 0.5(모름) 고정이 되면 점수가 바뀌어 다른 부품이 뽑힌다 —
`main.py computer_pass` 기준:

| | 총액 | 리뷰 관측 |
| --- | --- | --- |
| 산출물 있음 | **1,439,000원** | 3/8 슬롯 |
| 산출물 없음 | **1,378,000원** | 0/8 슬롯 |

테스트(96 passed)와 `check_skeleton` 은 **양쪽 다 통과**한다. 그러니 숫자가 다르다고 깨진 게 아니다.
어느 쪽인지는 `[3-B]` 로그 첫 줄로 확인한다 — 산출물을 못 쓰면 경고가 나온다:

```
⚠ 리뷰축 비활성 — 산출물 미탑재 — pcparts_product_risk.json (리뷰 관측 0건으로 계산)
```

**못 쓰는 경우가 넷이고 원인을 구분해 말한다**(`risk_store_reason()`): 파일 없음 · 형식 아님 · 전송 중 잘림 ·
**대조군 범위 불일치**. 마지막 것은 `meta.control_scope` 가 `config.REVIEW_RISK_CONTROL_SCOPE` 와 다를 때다 —
유아용품 대조군을 PC 추천에 물리면 에러 없이 **틀린 중앙값과 비교한 관측 사실**이 나오므로, 아예 쓰지 않는다.
넷 다 추천을 죽이지 않는다(전에는 잘린 파일이 `KeyError` 로 추천 전체를 죽였다).

## 관측 사실이 화면에 나가는 자리

`reasoning_log`(추천 과정 기록)와 `explanation_text` 다. 프론트의 **「추천 과정 보기」** 타임라인에 그려진다:

```
▸ [리뷰 관측]              리뷰 관측 3/8 슬롯
▸ [리뷰 관측 · 케이스]      케이스 관측 사실 3건 (점수 아님)
     리뷰 449건 중 15건(3.3%)이 7일 안에 몰림 — 전체 상품 중앙값 5.5% ·
     리뷰어 411명이 다른 상품에서도 함께 나타남 (연결 상품 4246개) — 중앙값 60명 / 903개 ·
     5점 비율 77% — 중앙값 67% — 확인: https://www.amazon.com/dp/B0BFH9M9CY
```

슬롯마다 한 단계로 나눈다 — 화면이 `detail` 을 한 단락으로 그려서, 세 슬롯의 문장 아홉 개를
한 단락에 넣으면 읽을 수 없다. 관측이 하나도 없으면 단계를 만들지 않는다("깨끗했다" 와
"볼 리뷰가 없었다" 는 다른 말이다).

**쓰지 않은 자리 둘, 이유와 함께:**

- `ItemOut.review`(`ReviewBriefOut`) — 필드가 `total_count` · `excluded_ratio` · `rating_refined` 이고
  **셋 다 필수**다. 뒤 둘은 결정 0001 로 낼 수 없다. "제외 0건" 으로 채우면 화면이
  "조작 제외 전후 평점" 으로 그려서 **클렌징이 돌아 아무것도 못 찾은 것처럼** 읽힌다.
  그래서 비워 둔다 — 부품 카드 라벨이 "리뷰 정보 없음" 으로 나오는 것이 이 때문이다.
  **두 필드를 선택(nullable)으로 바꾸면** `리뷰 449건` 만 띄울 수 있다. 단 프론트가
  `(review.excluded_ratio || 0)` 로 `null` 을 0 으로 단정하므로 그쪽도 같이 고쳐야 한다
- `ItemOut.checks`("구매 전 확인") — [3-C] 스펙 검증 문장의 자리다. 섞으면 나중에 서로 덮는다

**`product_key` 주의.** `GET /session/{id}/result` 는 `catalog.product.model`(제품명 원문)을
`product_key` 로 내보내는데 `[3-B]` 후보는 슬러그를 쓴다(`catalog.product` 에 슬러그 컬럼이 없어
저장할 때 사라진다). 그래서 화면의 리뷰 버튼이 전부 404 였다. `review_service.candidate_keys()` 가
받는 쪽에서 흡수하지만, **근본 해결은 결과 조립이 슬러그를 내보내는 것**이다. 지금은 변환 규칙이
`catalog_repo` 와 `review_service` 두 곳에 있어 갈리면 다시 404 가 된다.

## 규칙 기반 "의심 지표 2개+ 리뷰 수" — `data/review_suspect_counts.json`

데모에 숫자를 보여 달라는 요청으로 넣었다. **조작으로 판정된 리뷰 수가 아니다.** 리뷰 하나가
아래 다섯 중 **2개 이상**에 걸리면 센 것이고, 리뷰 단위 정답 라벨이 없어 **정밀도를 잴 수 없다.**

| 지표 | 정의 |
| --- | --- |
| 몰림 | 그 상품 리뷰가 가장 촘촘한 7일 창 안 |
| 다작 계정 | 쓴 계정의 전역 리뷰 30건+ |
| 1건 계정 | 쓴 계정의 전역 리뷰 1건뿐 |
| 단기 활동 | 계정 활동 기간 30일 이하 (2건+) |
| 구매 미확인 | 플랫폼이 확인하지 않음 |

파일이 **자기 방법과 한계를 담고 있다**(`method` · `limits` · `baseline`). 5.8KB 라 커밋돼 있어
따로 전달할 필요가 없다. 없으면 이 문장을 **아예 내지 않는다**(0건으로 단정하지 않는다).

문장에는 **건수 · 이항 95% CI · 전체 기준선**이 항상 같이 나간다:

```
리뷰 30건 중 5건(16.7%)이 의심 지표 2개 이상에 걸림 (데모 상품 전체 3.1%)
  — 95% 신뢰구간 [5.6, 34.7] · 기준선 초과
     출처: 규칙 기반 집계 — 조작 판정 아님 (지표 2개+, 정답 라벨 없음)
```

**CI 를 빼고 내보내면 안 된다.** 데모 16개 상품 중 CI 하한이 기준선을 넘는 것은 **3개뿐**이고,
n=37 의 21.6% 는 CI 가 [9.8, 38.2] 다 — 숫자만 보면 "평균의 7배" 인데 실제로는 "3배에서 12배 사이" 다.
나머지 13개는 기준선과 구별되지 않아 문장이 그렇게 말한다.

**임의성 넷** — 팀에 공유할 때 같이 말한다. (1) "2개 이상" 은 근거로 정한 값이 아니다
(2) 지표가 서로 배타적이라 실제로는 (몰림 또는 미확인)+(계정 유형) 조합이다 (3) 대상 계정의
전역 리뷰 중앙값이 6건인데 데이터 전체는 1건이다(선택 효과) (4) 구매 미확인을 단독 유죄 증거로
쓰지 않기로 했는데 조합의 한 축으로 넣은 것은 타협이다(무상 제공 프로그램이 설계상 미확인이다).

## 이 모듈이 내지 않는 것

- **정제 후 평점 · 정제 비율** — `cleaned_rating` · `cleanse_ratio` 는 항상 null (결정 0001). 상품 단위 신호라
  리뷰를 하나도 빼지 않는다. `evidence.review_aggregate` 의 "클렌징 후" 칸은 이번 사이클에 채워지지 않는다
- **개별 리뷰의 진위** — 출력은 상품에 붙는 관측 사실과 확인 경로. 점수(`score`)는 어디에도 없다
- **탐지율** — 데모 데이터(Amazon'23)에는 조작 라벨이 없다. 문턱("중앙값 2배")은 영어 실측 라벨에서 방향만 확인했다

## 확인 순서 (일요일)

1. `uv sync --group review-analysis --group test` → `PYTHONPATH=. uv run pytest -q` (관계 축 14건 포함 green)
2. `pcparts_product_risk.json` 을 `data/amazon23/` 에 두고 `uv run python -m src.workers.review_cleanse_worker --lookup amd-ryzen-5-5600`
3. API 띄워 `GET /reviews/summary/amd-ryzen-5-5600` — 실측 블록 + 데모 블록이 분리돼 나오는가
4. `uv run python main.py computer_pass` — 결과표 아래 "리뷰 관측" 줄, 총액이 바뀐다(리뷰축이 순위에 들어가므로)
5. 실 DB 로 끝까지: `docker run -d --name truefit-pg -e POSTGRES_USER=truefit -e POSTGRES_PASSWORD=truefit
   -e POSTGRES_DB=truefit -p 5433:5432 pgvector/pgvector:pg16` → `DATABASE_URL=...:5433/truefit python db/setup_all.py`
   → `uvicorn src.api:app`. 브라우저에서 컴퓨터 → 조건 → 추천 → **「추천 과정 보기」** 에 리뷰 관측 단계가 뜬다.
   (5432 에 다른 PostgreSQL 이 있으면 포트를 비켜 쓴다)
