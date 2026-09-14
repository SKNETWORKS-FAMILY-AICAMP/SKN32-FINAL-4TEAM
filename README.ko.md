# TrueFit — 목적성 쇼핑 플래너

[English](README.md) · **한국어**

> *"150만 원쯤으로 조용한 게임용 PC."* — *"8개월 아기 외출에 필요한 것 전부."*
> TrueFit은 이런 목적을 예산에 맞춘 구매 목록으로 바꾸고, 이유·아직 열린 확인 항목·리뷰 데이터가 실제로 보여주는 것을 함께 내놓습니다. 결정은 사람이 합니다.

**Strands Agents SDK**로 만들었고, AWS *Agents for Humans* 해커톤 **Everyday Agents** 트랙(집·돈·가족)에 냅니다. MIT 라이선스.

## 문제

목적이 있는 구매는 매번 반복되는 조사 노동입니다. PC 조립은 서로 맞아야 하는 부품 8개(소켓·전력·크기)와 예산이고, 유아용품은 아이의 월령·체중과 리콜·인증에 따라 안전이 갈리는 열몇 가지 품목입니다. 사람들이 기대는 두 정보원이 가장 믿기 어렵습니다 — 조작될 수 있는 리뷰 점수, 그리고 이유 없이 숫자만 주는 추천 사이트.

TrueFit은 세 가지를 거부하는 데서 출발합니다.

1. **방법 없는 판정은 없다.** 리뷰가 허위라거나 어떤 부품이 "최고"라고 말하지 않습니다. 확인 가능한 것만 냅니다 — *"리뷰 209건 중 60건이 한 7일 창에 몰림, 부류 중앙값 5.5%"* — 판단은 읽는 사람의 몫입니다.
2. **숫자는 코드, 말은 모델.** 순위·검증·예산 계산·저장되는 모든 값은 코드가 계산합니다. 언어 모델은 자유 텍스트를 구조화된 조건으로 바꾸고, 저장된 사실을 문장으로 바꾸는 일만 합니다.
3. **에이전트는 제안하고 사람이 결정한다.** 모든 추천은 편집할 수 있고, 모든 편집은 같은 저장된 계획 위의 도구 호출이며, 아무것도 대신 사지 않습니다 — 링크는 판매처로 갑니다.

## 무엇을 하나

카테고리 → 조건 대화 → 추천 → 확정 → 리포트, 브라우저 한 흐름입니다. 저장하기 전까지 로그인은 필요 없습니다.

| 단계 | 하는 일 |
|---|---|
| **조건** | 필수 항목은 칩으로, 나머지는 자유 텍스트로. Strands 에이전트가 *"조용한 게임용 PC, 150만 원쯤, 엘든링, 가능하면 흰색 케이스"* 를 타입·검증을 거친 조건으로 바꾸고 빠진 것을 이어서 묻습니다 |
| **추천** | 엔진이 슬롯별 후보를 만들고, 거르고, 순위를 매기고(리뷰 관측은 강등만, 제외 없음), 세트를 최적화하고, 검증하고, 신뢰도가 낮으면 한 번 재탐색합니다. 품목마다 이유, 사용 가이드를 인용한 *구매 전 확인*, 리뷰 관측 한 줄이 붙습니다 |
| **말로 편집** | *"CPU 더 싼 걸로 바꾸고 GPU는 왜 골랐는지 알려줘"* — 두 번째 Strands 에이전트가 대안을 조회하고, 교체하고, 수량·시점을 바꾸거나, 저장된 근거로만 설명합니다 |
| **확정·리포트** | 이름·구매 예정일·목표 금액·메모. 확정 스냅샷은 판매처 링크와 선택 사항인 목표가 추적을 유지합니다 |

두 도메인이 엔진을 공유합니다. **PC 조립**(세트를 최적화한 뒤 전체를 검증)과 **유아용품**(품목마다 설명서·리콜·인증 규칙으로 먼저 검증한 뒤 예산 배분). UI와 서버 모두 한국어·영어를 쓰며, 영어 세션은 단위 없는 예산을 달러로 읽습니다.

## 화면

<table>
<tr>
<td width="50%"><img src="docs/screenshots/02-conditions.png" alt="조건 대화: 자유 문장 하나가 타입 있는 조건이 된다"><br><sub>문장 하나 → 용도·예산($1,500 → USD)·우선순위·게임 제목·자유 조건("흰색 케이스") — 전부 조건 에이전트가 검증된 도구 호출로 설정.</sub></td>
<td width="50%"><img src="docs/screenshots/03-results.png" alt="추천 요약"><br><sub>설명은 저장된 사실로만 생성되고, 못 한 것도 말한다: 추가 요청은 자동 반영되지 않았고 확인 항목 둘은 아직 미검증.</sub><br><br><img src="docs/screenshots/04-result-chat.png" alt="결과 대화: CPU 교체와 GPU 설명"><br><sub>결과 에이전트가 버튼과 같은 서비스로 교체한 뒤 저장된 이유로 GPU를 설명.</sub></td>
</tr>
</table>

스크린샷은 2026-09-14 실제 세션(`gpt-4o-mini`, 합성 카탈로그)입니다. 데모의 가격은 **합성**이며 UI가 그렇게 표시합니다.

## Strands Agents 위에서

에이전트 둘, 모두 opt-in, 모두 요청마다 계획의 현재 상태를 도구 안에 담아 새로 만듭니다.

| 에이전트 | 턴 | 도구 | 코드가 강제하는 것 |
|---|---|---|---|
| **조건 에이전트** — [`src/agent/conditions_agent.py`](src/agent/conditions_agent.py) | `POST /session/{id}/message` | `set_condition` · `add_extra_condition` · `clear_condition` | `config/categories/<cat>.yaml`의 `slot_schema`에 있는 필드만 존재합니다. enum·타입·범위·통화는 도구 안에서 검사하고, 틀린 값은 오류 문자열로 돌아가 모델이 고칩니다. 무엇이 필수이고 다음에 무엇을 물을지는 도구 호출마다 서비스가 다시 계산해 넘겨줍니다. 에이전트는 DB를 만지지 않습니다 — 패치는 `session_service`가 규칙 경로와 같은 origin 표지로 적용합니다 |
| **결과 에이전트** — [`src/agent/result_agent.py`](src/agent/result_agent.py) | `POST /session/{id}/result-message` | `list_alternatives` · `swap` · `set_qty` · `set_timing` · `remove_or_restore` · `explain` | 모든 도구가 기존 서비스 호출을 감싸므로 소유권 검사와 합계 재계산이 버튼과 같습니다. `swap`은 서비스가 그 품목에 대해 아는 후보만 받습니다 — 지어낸 id는 거부됩니다. `explain`은 저장된 이유·예산 비중·검증 쟁점·리뷰 관측을 돌려줍니다 — 부품이나 리뷰에 점수를 매길 수 없습니다 |

```python
@tool
def set_condition(field: str, value: str) -> str:
    """조건 필드 하나를 설정한다. 금액은 사용자가 말한 단위 그대로("$1,500", "150만원") — 환산은 코드가 한다."""
    return draft.set(field, value)        # 카테고리 스키마로 검증; 실패하면 오류 문자열을 돌려준다

agent = Agent(
    model=OpenAIModel(client_args={"api_key": OPENAI_API_KEY}, model_id=LLM_MODEL, params={"temperature": 0.2}),
    system_prompt=system_prompt(draft, text, history),   # 필드 목록, 칩→값 매핑, 남은 필수 항목
    tools=make_tools(draft),
    messages=_history(history),
    tool_executor=SequentialToolExecutor(),                # 도구들이 한 draft 를 순서대로 고친다
)
result = agent(text)                                       # 사람에게 줄 답변; draft.patches 는 서비스가 쓴다
```

이 구성에서 뻔하지 않은 점:

- **상태를 바꾸는 길은 도구뿐이고, 도구는 API처럼 검증된다.** `"$1,500"`은 `budget_max=2,100,000 KRW` + `currency=USD`가 되고, 우선순위 필드에 `"purple"`을 넣으면 허용값(`performance`, `value`, `quiet`)을 적은 오류가 돌아와 모델이 다시 부릅니다. 모든 호출과 결과는 턴마다 기록됩니다.
- **무엇이 필수인지는 에이전트가 아니라 서비스가 정한다.** 도구 호출마다 결과에 다시 계산한 빠진 항목 목록과 다음 질문이 실리므로, 모델은 규칙 엔진이 물었을 것을 정확히 묻고 `can_recommend`가 켜지면 멈춥니다.
- **결과 에이전트는 대화 기록이 아니라 저장된 계획 위에서 움직인다.** 교체와 편집은 UI 버튼과 같은 코드 경로를 지나 화면에 바로 보입니다. 교체가 조용히 재검증되지는 않습니다 — 도구 결과가 그 사실을 적고 에이전트가 그대로 전합니다.
- **같은 모델, 두 가지 일, 하나의 규칙.** 엔진은 같은 OpenAI 클라이언트로 검증 쟁점 문장과 설명을 쓰지만, 자신이 계산한 사실만 넘깁니다. 모델을 끄면(`MOCK_MODE=1`) 숫자는 하나도 안 바뀌고 문장만 자리표시로 바뀝니다.

켜기: `MOCK_MODE=0 · LLM_PROVIDER=openai · LLM_MODEL · OPENAI_API_KEY` + `CONDITIONS_AGENT=1` / `RESULT_AGENT=1`. 모델 제공자는 함수 하나(`_model()`)라 Strands의 Bedrock 모델 클래스를 그 자리에 끼우면 됩니다. 설계 문서: [조건 대화 에이전트](docs/조건대화_에이전트_strands.md) · [결과 화면 에이전트](docs/결과화면_에이전트_strands.md).

## 어떻게 동작하나

![아키텍처](docs/architecture.png)

<details>
<summary>Mermaid 원본</summary>

```mermaid
flowchart LR
  U["사람<br/>브라우저, 한국어 또는 영어"]
  subgraph App["TrueFit — FastAPI, 단일 오리진, 작업 38개"]
    direction TB
    SVC["서비스<br/>session · recommendation · lists · auth · reviews"]
    subgraph Strands["Strands Agents SDK"]
      CA["조건 에이전트<br/>set_condition · add_extra_condition · clear_condition"]
      RA["결과 에이전트<br/>list_alternatives · swap · set_qty · set_timing<br/>remove_or_restore · explain"]
    end
    ENG["추천 엔진<br/>요구사양 → 후보 → 하드필터 → 순위<br/>→ 최적화 ⇄ 검증 → 설명"]
  end
  subgraph Ev["근거"]
    RX["리뷰 관계·행동 축<br/>Amazon Reviews'23 → 상품별 관측 사실"]
    CG["사용 가이드 RAG<br/>18건, 인메모리 임베딩"]
    MR["설명서 검색 제공자<br/>local-file, RDB 밖"]
  end
  DB[("PostgreSQL 16<br/>스키마 10 · 테이블 38")]
  LLM["OpenAI (Strands OpenAIModel)<br/>chat + embeddings"]
  U -- "자유 텍스트, 칩, 편집" --> SVC
  SVC --> CA
  SVC --> RA
  SVC --> ENG
  CA -- "스키마로 검증된 패치" --> SVC
  RA -- "기존 서비스 호출만" --> SVC
  ENG --> RX
  ENG --> CG
  ENG --> MR
  ENG -- "쟁점 문장 · 설명" --> LLM
  CA --> LLM
  RA --> LLM
  SVC --> DB
```

</details>

- **엔진**(`src/engine`): 의도 → 요구사양 → 후보 → 하드필터 → 순위 → *(PC)* 세트 최적화 ⇄ 검증, 신뢰도 문턱 아래면 한 번 재탐색 / *(유아)* 품목별 검증 → 예산 배분 → 설명. `POST …/recommend`는 즉시 `202`를 돌려주고, 실행이 요구사양·후보·검사·설명을 저장하며 `GET …/result`로 폴링합니다.
- **리뷰 근거**(`src/workers/relation_axis.py`): 리뷰 본문을 한 줄도 읽지 않고, Amazon Reviews'23(리뷰 4,390만 건, 계정 1,830만 개) 배치가 상품별 관측을 냅니다 — 가장 붐빈 7일 창에 몰린 리뷰 비율, 다른 상품과 공유하는 리뷰어, 리뷰가 한 건뿐인 계정, 구매 확인 비율 — 각각 같은 상품 부류의 중앙값과 대조합니다(리뷰 30건 이상 PC 부품 11,457개; 7일 몰림 중앙값 5.5%, 99백분위 20.5%). 조작 라벨이 없으므로 **탐지율도 "정제" 평점도 없습니다**([결정 0001](docs/decisions/0001-정제-후-평점을-판정기-없이-내지-않는다.md)). 관측은 순위에서 후보를 강등할 뿐 제외하지 않습니다.
- **구매 전 확인**(`src/rag/care_guides.py`): 합성 부품 사용 가이드 18건을 기동 시 인메모리로 임베딩하고 품목마다 가장 가까운 문장을 인용합니다.
- **유아 설명서**(`src/rag/provider.py`): 설명서는 PostgreSQL *밖*의 검색 제공자에 게시합니다(`rag` 스키마는 멘토 검토 뒤 삭제). local-file 구현이 들어 있고 호스팅 저장소가 다음 단계입니다. 좌석 조건(6개월 이상·22kg 이하·혼자 앉기)은 검수된 문장에서만 확인하고, 제공자가 없으면 *unknown*이지 조용히 통과가 아닙니다.
- **프론트**(`frontend/`): API가 같은 오리진에서 서빙하는 정적 페이지 10개. 모든 값은 API에서 오고, 쿠키는 httpOnly, 한국어/영어 토글이 UI와 서버 언어를 함께 바꿉니다.

## 돌려보기

Python **3.11**과 [`uv`](https://docs.astral.sh/uv/). 설정은 환경변수로, 없으면 `.env`(`.env.example`에 목록).

**A. 콘솔 — DB도 키도 없이**

```bash
uv sync --locked
uv run python main.py computer_pass        # 8개 슬롯, 검증 1회 통과 (목 LLM, 주입된 점수)
uv run python main.py computer_research    # 점수 72 → 후보 교체 → 86
```

**B. 웹 UI + PostgreSQL**

```bash
cp .env.example .env                        # MOCK_MODE=1, 에이전트 꺼짐
docker compose up -d db
export DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit
uv run python db/setup_all.py                                # 마이그레이션 15개 · 도메인 · PC 부품 51개 · 리뷰 요약
uv run python scripts/generate_and_seed_baby_catalog.py      # 합성 유아용품 188개
uv run uvicorn src.api:app --reload --port 8000              # http://127.0.0.1:8000 · API 문서 /docs
```

DB 표준 문서는 [`db/README.md`](db/README.md)(Docker 없이 conda로 하는 방법 포함).

**C. 실제 모델과 에이전트** — `.env`에 `MOCK_MODE=0`, `LLM_PROVIDER=openai`, `LLM_MODEL=gpt-4o-mini`, `OPENAI_API_KEY=…`, `CONDITIONS_AGENT=1`, `RESULT_AGENT=1`. 테스트도 `.env`를 읽으므로 `MOCK_MODE=1 uv run python -m pytest -q`로 돌립니다.

**D. Docker** — `docker compose up -d --build`(db + api) 뒤 `docker compose exec api python db/setup_all.py`. `JWT_SECRET`을 바꾸고(`APP_ENV=production`이면 개발 기본값을 거부), HTTPS 뒤에서는 `COOKIE_SECURE=1`, UI가 다른 오리진에 있을 때만 `ALLOWED_ORIGINS`. 이미지에 `scripts/`가 없으니 유아 시드는 호스트에서.

## 현재 상태 — 2026-09-14 실측

| | 되는 것 | 아직 |
|---|---|---|
| PC | 전체 흐름: 조건 → 실행 → 이유·확인·리뷰 줄·대안·교체·수량/시점·결과 대화 → 확정 → 리포트 → 목표가 추적, 전부 저장 | 합성 가격. 호환은 근사(소켓·전력·크기). 교체 뒤 재검증 없음 |
| 유아 | 조건 → 실행 → 품목별 후보와 안전 검사 → 배분 | 함께 든 합성 카탈로그에 검수된 안전 규칙이 없어 **게이트를 통과하는 후보가 없음** — 실행은 *done*, 선택 0건. 기제는 돌고, 데이터가 아직 고르게 해 주지 않음 |
| 에이전트 | 실제 세션에서 둘 다(위 스크린샷). 영어·한국어 | OpenAI 키 필요. 사전 기반 UI 번역이라 동적 문장 일부는 한국어로 남음 |
| 계정 | 이메일+비밀번호, httpOnly JWT, 게스트 → 계정 병합, 탈퇴 | 이메일 인증·비밀번호 재설정은 미룸. `/auth/request-code`, `/auth/verify`는 스텁 |
| 리뷰 | 데모 부품 51개 중 25개의 관계 축 관측이 순위·설명·`GET /reviews/summary`에 | 리뷰 *작성*은 데모 범위 밖. 실제 소스 수집기 없음 |
| 데이터 | 스키마 10 / 테이블 38, 원샷 셋업, RDS 호환 SQL | 실시간 가격·스펙 연동 없음. 알림·학습 워커는 스텁 |

새 시드 DB·목 모델에서 테스트 **402 passed, 17 failed, 8 skipped**(8초). DB 없이 264 passed, 162 skipped, 1 failed. 실패 내역은 아래. 같은 날 손으로 확인: PC·유아 HTTP 흐름, 콘솔 시나리오, `rag_manual.py` 21/21, 스크린샷의 영어 세션.

<details>
<summary>실패 17건의 원인</summary>

- 6 — 병합 전 결과 형태(품목별 `status`)를 전제한 유아 트랙 HTTP 테스트
- 7 — 아직 충족 못 한 인증 강화 수용 테스트: `email-availability` 속도 제한, 잠금 카운터 초기화, 비밀번호 변경 직후 JWT 무효화, 탈퇴 시 동의 시각 삭제
- 2 — 이중 확정 / 잠금 버전 충돌이 기대와 달리 안 남
- 1 — 유아 요구사양 형태. 1 — 마이그레이션 목록을 옛 `develop` 커밋에 고정(`0014_candidate_checks.sql`을 drift로 봄 — 낡은 건 테스트)
- 건너뜀: pandas 미설치(2), 전용 일회용 DB를 요구하는 테스트(6)
</details>

<details>
<summary>API (작업 38개, <code>/docs</code>)</summary>

| 그룹 | 작업 | 상태 |
|---|---|---|
| `/session` (14) | 생성, 조회, category, slot, message, answer, reset, spec-file, recommend (202), result, 품목 patch, alternatives, swap, result-message | 동작, 로그인 불필요 |
| `/lists` (6) | 목록, 이름 변경, 삭제, confirm (`If-Match`), report, alert | 동작. 확정·리포트·알림은 로그인 |
| `/auth` (10) | signup, login, logout, me (GET/PATCH), password, withdraw, email-availability | 동작. request-code, verify → 501 |
| `/reviews` (5) | summary/{product_key} (엔진 키·요약 키·ASIN); pending, part, publish | 동작. build → 501 |
| `/dev` (2), `/health` | DB 없는 시나리오 실행; 생존 확인 | 공개 전 `/dev`를 막을 것 |

오류 봉투는 하나: `{"error": {"code", "message", "field"}}`. 프론트 계약: [`docs/frontend_외부수정요청.md`](docs/frontend_외부수정요청.md).
</details>

## 다음

1. 자기 게이트를 통과하는 유아 카탈로그 — 부류별 검수된 안전 규칙, 합성 상품의 인증·리콜 데이터.
2. `src/rag/provider.py` 뒤의 호스팅 벡터 저장소, 그다음 PC 검사에도 설명서 근거.
3. 테스트가 이미 적어 둔 인증 강화. 이메일 인증과 비밀번호 재설정.
4. 교체 뒤 재검증. 실제 스펙·가격 연동. 정확한 호환 규칙.
5. 첫 레코드부터 작성자 해시·게시 시각·옵션 단위 대상을 잡는 리뷰 수집기([수집 시점에 잡을 것](docs/review_collector.md)), 그다음 라벨링 규약 — 그 뒤에야 정제 평점.
6. 가격 추적과 알림(워커는 스텁).

<details>
<summary>저장소 구성</summary>

```text
main.py                       콘솔 파이프라인 (시나리오 파일, 목 LLM)
src/api.py, routers/          FastAPI 앱, 라우터 5개, frontend/ 서빙
src/services/                 session · recommendation · list · auth · review · feedback
src/agent/                    Strands 에이전트: conditions_agent.py, result_agent.py
src/engine/                   단계 [1]~[6], slot_rules(키워드 경로), prompts, lang
src/rag/                      care_guides(인메모리 RAG) · provider(검색 경계) · verification
src/repo/, src/db/, src/auth/ SQL 저장소 · psycopg 풀 · JWT/argon2/Origin 검사
src/workers/                  review_cleanse_worker + relation_axis(배치). 나머지 워커는 스텁
config/categories/            computer.yaml · baby.yaml(슬롯·질문·모드) + 유아 규칙
frontend/                     페이지 10개, css/, js/ (api.js · core.js · planner-shell.js · i18n.js · pages/)
db/                           migrate.py · 마이그레이션 15개 · seed*.py · setup_all.py · README.md
scripts/                      카탈로그·설명서 생성기 · rag_manual.py · Amazon'23 배치 · 스펙 수집기
data/, generated/, docs/      부품 목록·사용 가이드·시나리오 · 예시 산출물 · 명세·계약·결정
tests/                        파이프라인 · 에이전트 · HTTP 흐름 · 서비스 · SQL/마이그레이션 검사
```
</details>

## 문서와 라이선스

MIT — [`LICENSE`](LICENSE). 팀 문서: [DB 셋업](db/README.md) · [테이블 명세](docs/db/table_spec.md) · [스키마 축소](docs/db/db_schema_reduction_proposal_2026-09-12.md) · [API 계약](docs/frontend_외부수정요청.md) · [프론트 규칙](frontend/CLAUDE.md) · [결정 기록](docs/decisions/README.md) · [리뷰 분석 계약](docs/review_analysis_contract.md) · [유아 작업 패키지](docs/agent-tasks/baby/README.md) · [설명서 생성기](docs/synthetic_manual_generator.md). [`docs/rag_implementation.md`](docs/rag_implementation.md)는 삭제된 pgvector 설계를 적은 것으로 기록용으로만 남깁니다.
