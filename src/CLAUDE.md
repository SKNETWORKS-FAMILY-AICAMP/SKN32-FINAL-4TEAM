# LLM 연동 작업 지침 (`sllm` 브랜치)

## 이 문서의 범위

이 문서는 **LLM 연동에 해당하는 파일만** 다룬다. `src/` 전체에 대한 지침이 아니다.

| 파일 | 역할 |
|---|---|
| `src/clients/llm_client.py` | LLM API 호출 래퍼 (`call_llm`) |
| `src/engine/prompts.py` | 시스템 프롬프트 문안 |
| `src/engine/stage3c_verify.py` | [3-C] 검증 쟁점 문장 |
| `src/engine/stage5_explain.py` | [5] 추천 설명 문장 |
| `src/agent/conditions_agent.py` | 조건 대화 에이전트 (Strands Agents SDK) — 2026-09-14 스파이크, [[docs/조건대화_에이전트_strands.md]] |
| `src/agent/result_agent.py` | 결과 화면 대화 에이전트 (Strands) — 2026-09-14, [[docs/결과화면_에이전트_strands.md]]. 03 결과 화면(요약·입력칸·추천 이유)은 2026-09-14부터 사용자 담당 |
| `src/config.py`, `.env.example`, `requirements.txt`, `pyproject.toml` | 설정·의존성 (공용 파일) |

**`src/`의 나머지는 다른 팀원 소유다.** 2026-09-13 브랜치 비교 기준:

- `src/rag/`, `src/repo/rag_repo.py` → `rag` 브랜치
- `src/services/`, `src/routers/`, `src/repo/` → `develop` 브랜치 (세션·추천 서비스가 더 진행돼 있음)

필요해서 읽는 건 괜찮지만 고치지 않는다. 고쳐야 하면 먼저 사용자에게 알린다.

## LLM 사용 범위 — 확정 사항 (§D-3, 2026-09-11)

| 단계 | LLM | 비고 |
|---|---|---|
| [1] 채팅 조건 추출 | **사용 안 함** | 규칙 기반(`src/engine/slot_rules.py`) + 질문 칩 |
| [3-C] 검증 쟁점 문장 | **사용** | |
| [5] 추천 설명 문장 | **사용** | |

**[1]에 LLM 슬롯필링을 추가하지 않는다.** 프론트가 이 전제로 구현돼 있고(`frontend/CLAUDE.md`: "채팅 조건 추출에 LLM을 쓰지 않는다"), 프론트와 합의된 결정이다 (계약 문서 §D-3). 그 문서(`docs/frontend_외부수정요청.md`)는 2026-09-13에 로컬에서 삭제됐으므로 내용을 봐야 하면 `origin/develop` 또는 `origin/front`에서 꺼낸다. `stage1_intent.py`의 `NotImplementedError`는 미완성이 아니라 의도된 상태다.

**단, 2026-09-14 예외 — 조건 대화 에이전트 스파이크.** 해커톤이 Strands Agents SDK 사용을 제출 정의로
두고 있고 9/13 회의가 "에이전트 부재"·"추가 조건 미반영"을 지적해서, `src/agent/conditions_agent.py`가
`/session/{id}/message`의 자유 텍스트를 Strands 도구 호출로 조건에 반영한다. **기본은 꺼짐
(`CONDITIONS_AGENT=0`)** — §D-3 합의가 바뀌기 전까지 opt-in이고, API 계약(`ConditionState`·질문 칩)은
안 바뀐다. 켜는 결정은 프론트 담당자 합의 뒤에. 이 스파이크는 `src/services/session_service.py`
(`develop` 소유)의 `handle_message`에 12줄을 **추가**했다 — develop 담당자에게 알려야 한다.

## [3-C] 검사AI·변호인AI 디베이트는 쓰지 않는다

`stage3c_verify.py`의 `_debate_lines`와 `Issue.prosecutor`/`defender` 필드는 **남아 있는 옛 설계다.** 기획서 §10-12에서 디베이트가 걷혔고(비용 1/2), 그 자리는 **리뷰 관계·행동 축(review cleansing)** 이 대체했다. 검사/변호인 2인 프롬프트를 새로 만들지 않는다.

## 리뷰 관계·행동 축과의 접점 (`develop`, 2026-09-12~13)

`develop` 브랜치가 **우리 파일 둘을 이미 고쳤다.** [5] 작업은 develop을 받은 위에서 시작한다.

- `stage5_explain.run(build, verification, log, rank=None)` — **`rank` 키워드가 추가됐다.** 빼고 호출하면 리뷰 관측이 전 슬롯 "없음"이 되는데, 기본값이 `None`이라 **조용히** 그렇게 된다.
- `Explanation.review_line_by_slot`과 `items[].evidence`는 **이미 규칙으로 채워진다.** [5] LLM 문장을 붙일 때 이 값들을 덮어쓰거나 LLM이 다시 쓰게 하지 않는다. LLM이 만드는 건 `headline`·`items[].reason`·`caveats`뿐이다.
- `stage3b_rank.py`의 리뷰축(0.5 모름 / 0.75 관측됨 / 0.25 검토 필요)과 `REVIEW_OBS:` 플래그는 **담당 3의 자리다.** 순위 규칙을 건드리지 않는다.
- `src/services/review_service.py`의 `explanation_text_with_caveats()`가 `explanation_text`를 조립한다. LLM 문장을 넣더라도 이 경로를 우회하지 않는다.

### LLM에게 물으면 안 되는 것 (결정 0001)

**"이 리뷰가 조작인가"를 LLM에게 묻는 것은 금지다.** 사람 정확도 50.8%, GPT-4o 50.0%인데 확신도는 85.6으로 나온다(Hidden Persuaders, arXiv 2506.13313). 리뷰 진위 판정기가 없어서 `cleaned_rating`·`cleanse_ratio`는 **항상 null**이다. 프롬프트가 "조작"·"가짜 리뷰" 같은 판정을 만들어내면 결정 0001을 깬다.

리뷰 문장의 원칙은 [3-C] 원칙과 같다 — **관측 사실과 확인 경로만, 판정은 없다.** "상품 단위 신호이며 개별 리뷰의 진위가 아닙니다" 주의 문구가 항상 따라붙는다.

## 벤더와 설정

- **Bedrock은 쓰지 않는다. OpenAI만 쓴다** (2026-09-13 결정). 기획서·계약 문서가 전부 Bedrock Claude Haiku 기준으로 적혀 있으니, 문서를 근거로 Bedrock 경로를 만들지 않는다. 문서 쪽은 아직 미갱신이다.
- **코드에 벤더명·모델명을 박지 않는다.** 전부 env로 주입한다 (`LLM_PROVIDER`, `LLM_MODEL`, `OPENAI_API_KEY`). 기존 `src/config.py`의 컨벤션이다.
- `MOCK_MODE=1`이 기본이고 외부 호출을 전부 가짜로 대체한다. 실제 호출은 `MOCK_MODE=0`.
- **`.env`는 커밋하지 않는다** (`.gitignore`에 있음). API 키를 코드·문서·커밋 메시지·로그에 넣지 않는다. 키가 필요한 확인은 사용자에게 요청한다.
- 임베딩(RAG)은 **우리 범위 밖**이다 — `RAG_EMBEDDING_PROVIDER`로 따로 움직이고 `rag` 브랜치 소유다. `LLM_PROVIDER`와 무관하므로 LLM 작업하면서 건드리지 않는다.

## 프롬프트 규칙

- 문안은 `src/engine/prompts.py` **한 곳에만** 둔다. 스테이지 모듈에 문자열을 흩뿌리지 않는다.
- **[3-C]는 판정어 금지.** "위반·통과·불합격·안전합니다·부적합" 같은 판정을 LLM이 내리지 않는다. 판정과 감점은 규칙 엔진이 정하고, LLM은 관측값과 근거가 무엇인지만 중립 서술한다.
- **[5]는 수치·부품명·통과여부를 코드가 확정해 입력으로 준다.** LLM은 서술만 한다. 새 수치를 만들거나 반올림·환산하지 않는다. `items[].slot`은 실제 슬롯명과 일치해야 한다.
- 근거(evidence)가 0건이면 있는 것처럼 쓰지 않는다.
- **문안 변경은 팀 승인 대상이다** (기획서 §19-3 체크리스트에 미승인 항목으로 올라 있음). 임의로 고치지 말고 사용자에게 확인한다.

## 실패·지연 처리

- 구조화 출력은 **스키마 검증 후 실패 시 1회 재시도**, 그래도 실패하면 **규칙 템플릿 fallback**으로 내려간다 (§11-6).
- **[3-C] 문장 생성 실패는 신뢰도 점수에 영향을 주지 않는다** (§10-11 E4). 문장만 템플릿으로 대체한다.
- API 계약상 LLM 문장 필드는 `{"status": "pending" | "ready" | "failed", "text": ...}` 형태다 (§D-4-0, `src/schemas.py`의 `TextStatusOut`).
- **LLM 때문에 추천 결과 전체를 지연시키지 않는다.** 상품·가격은 먼저 응답하고 문장은 나중에 채운다.

## 코드 규칙

- `call_llm()` **시그니처를 바꾸지 않는다.** 호출부가 여러 곳이고 다른 브랜치와도 공유되는 파일이다.
- `MOCK_MODE` 분기와 목 응답 경로를 **깨지 않는다.** 기존 테스트가 이 경로로 돈다.
- LLM 응답은 **pydantic으로 검증하고 나서** 쓴다 (`src/dto.py` 경계). 검증 안 된 dict를 그대로 흘리지 않는다.
- 공용 파일(`requirements.txt`, `pyproject.toml`, `src/config.py`)은 **줄 추가만** 하고 기존 줄을 재배열·재정렬하지 않는다. 다른 브랜치와의 충돌 지점이다.
- 주석은 WHY만 짧게. 기존 파일의 한국어 docstring 스타일을 따른다.

## 실행과 검증

```powershell
uv run python -m pytest -q
uv run python main.py computer_pass
```

- 변경 후 **`MOCK_MODE=1` 회귀를 먼저** 확인한다.
- `psycopg`가 없는 환경에서는 `tests/test_frontend_static_serving.py`·`tests/test_rag_postgres.py`가 수집 단계에서 실패한다. 이건 기존 환경 문제이므로 제외하고 돌린다 — 현재 `sllm` 기준선은 **36 passed**다. develop을 병합하면 리뷰 축 테스트가 들어와 기준선이 올라간다(develop 기준 96 passed).
- **리뷰 산출물 유무로 추천 결과가 달라진다.** `data/amazon23/pcparts_product_risk.json`(5MB, `.gitignore`라 별도 전달)이 없으면 리뷰축이 0.5 고정이라 `main.py computer_pass` 총액이 1,439,000원 → 1,378,000원으로 바뀐다. **양쪽 다 테스트는 통과하므로 숫자가 다르다고 깨진 게 아니다.** `[3-B]` 로그 첫 줄의 `⚠ 리뷰축 비활성` 경고로 어느 쪽인지 확인한다.
- 실제 호출 확인은 `.env`에 키를 넣고 `MOCK_MODE=0`으로 최소 건수만 돌린다.
- **키가 없어 확인 못 한 흐름은 완료로 보고하지 않고 "미확인(키 대기)"로 명시한다.**

## 문서 갱신 의무

- LLM 관련 결정이 바뀌면 **프론트 담당자와 먼저 합의하고 계약 문서 §D-3에 기록한 뒤** 구현한다. 프론트가 그 문서를 계약으로 본다. 단 이 브랜치의 워킹트리에는 그 파일이 없다 — `origin/develop`·`origin/front`에 있다.
- 벤더 변경(Bedrock → OpenAI)은 아직 이 문서에 반영되지 않았다.

## 브랜치

- 작업 브랜치는 `sllm`이다. 원래 README만 있는 독립 히스토리였고, 2026-09-13에 `front`를 병합해(`--allow-unrelated-histories`) 최신 코드를 받았다. 같은 날 `develop`도 병합했다(충돌 없음).
- **git commit·push·branch 변경은 사용자가 요청할 때만 한다.**
- `develop`을 다시 받을 때는 먼저 `git merge-tree --write-tree HEAD origin/develop`으로 충돌을 예행연습한다 — 워킹트리를 건드리지 않고 exit 0/1로 답이 나온다.

## 남은 작업 (2026-09-13 기준 — 진행되면 이 절을 갱신할 것)

[3-C] 쟁점 문장화와 [5] 설명 문장은 **끝났고 실제 OpenAI 호출까지 확인**했다. 남은 것은 넷이다.

**1. 문장 필드 pending/ready/failed 분리 — develop이 반영, 머지 완료 (2026-09-13).**
`docs/개발요청_추천결과_부분저장.md` 요청대로 develop이 3e2a7ee에서 반영했다 —
`execute_recommendation`이 [2]~[4]+검증을 별도 트랜잭션으로 먼저 `complete_run`하고, [5]는
그 뒤 또 다른 트랜잭션에서 돌며 성공하면 `reason`/`explanation`을 `ready`로, 실패하면
`failed`로만 남긴다(`run.status`는 안 건드림). `origin/develop` → `sllm` 머지 확인,
`merge-tree` 예행연습·실제 머지 둘 다 충돌 없음.

머지 리뷰 중 버그 하나 발견해 바로 고쳤다(6e0bec1) — `get_stored_result`가
`reason_status`/`explanation_status`의 `'failed'`를 못 읽고 `ready`가 아니면 전부
`pending`으로 매핑하고 있었다. 이러면 [5]가 진짜 실패했을 때 프론트가 영원히
`pending`으로 보고 폴링을 안 멈춘다 — 없애려던 무한 로딩이 다른 경로로 재발하는 것.
DB 스키마(`db/migrations/0008_frontend_contract.sql`)는 처음부터 세 상태를 다 갖고
있어서 컬럼값을 그대로 옮기도록 2줄만 고쳤다. **develop 담당자에게 이 수정 사실을
알려야 한다** — 자기 커밋 위에 우리가 고친 것이므로.

**DB 없이는 실제 검증 못 함 — 미확인.** 이 환경엔 `psycopg`도 로컬 Postgres도 없어서
두 트랜잭션 분리가 실제로 의도대로 동작하는지(부품표가 [5] 전에 진짜로 조회되는지)는
코드 리딩으로만 확인했다. `pytest`는 기존 기준선(87 passed, 기존에도 실패하던
`test_list_service.py` 3건 제외) 그대로 유지되는 것만 확인.

**2. 프롬프트 문안 팀 승인 — 승인·반영 완료 (2026-09-13).**
`docs/프롬프트_개선_초안_설명문장.md`의 규칙 4(headline 신뢰도 숫자 명시)·규칙 7(평가어 목록
구체화)를 사용자 승인 받아 `EXPLAIN_SYSTEM`에 반영. `stage5_explain.py`의 코드 가드
둘(`_BANNED_IN_DRAFT`에 평가어 추가, headline 신뢰도 숫자 누락 시 fallback)도 같이 반영.
`MOCK_MODE=1` 회귀 확인(87 passed, 기존 실패 3건 제외 동일).

**3. 데모 시나리오에 `tool_result` 추가 — 완료 (2026-09-13).**
`computer_pass.json`·`computer_research.json`의 쟁점 다섯 건에 `tool_result`(관측값 문자열)를 채우고, 쓰지 않던 `prosecutor`/`defender`는 제거했다. `stage3c_verify._issue_sentence`의 프롬프트가 이제 "관측값: (기록 없음)" 대신 실제 값("상시부하 420W · 정격 대비 55%" 등)을 받는다. `MOCK_MODE=1`으로 `main.py computer_pass`·`computer_research` 둘 다 재확인, `pytest` 기준선(87 passed / 기존에도 실패하던 `test_list_service.py` 3건 제외) 그대로 유지.

**4. 팀에 알릴 것 둘 — 공지 문서 작성 완료 (2026-09-13).**
`docs/팀공지_LLM연동_참고사항.md`에 정리: (1) `recommendation_service.py`의
`message=issue.text or ...` 한 줄 변경(담당자 영역, 커밋 `1c76d94`) (2) 계약 문서 §D-3이
아직 Bedrock 기준이라 OpenAI 전환이 반영돼 있지 않다는 것. 프론트 담당자와의 계약 문서
갱신 자체는 sllm이 임의로 하지 않는다.

**5. `.env.example` 정리 — 완료 (2026-09-13).**
`LLM_REGION`·`EMBEDDING_MODEL`을 채워 둔 값이 `RAG_EMBEDDING_PROVIDER=bedrock` 기본값과
충돌할 수 있어(OpenAI 임베딩 모델명이 Bedrock 호출에 들어갈 위험) 둘 다 비웠다 — 실제
동작 중인 `.env`도 이미 이렇게 비어 있었다. Bedrock→OpenAI 결정 날짜를 주석으로 명시.
`EMBEDDING_MODEL`은 RAG 소유 변수라 값 자체는 안 건드리고 비활성화만 했다 —
`docs/팀공지_LLM연동_참고사항.md`에 rag 담당자 확인 필요 사항으로 같이 적었다.

**6. Strands 조건 대화 에이전트 — 스파이크 완료, 기본 꺼짐 (2026-09-14).**
`src/agent/conditions_agent.py` + `session_service.handle_message` 분기 + `tests/test_conditions_agent.py`(19건).
실측·경계·한계·같이 발견한 develop 버그(`db/seed.py`의 `shared.unit`)는 `docs/조건대화_에이전트_strands.md`.
켜려면 `.env`에 `CONDITIONS_AGENT=1`. 남은 결정 둘: (a) §D-3 갱신·기본값 켜기 — 프론트 담당자 합의
(b) `extra`(자유 조건)를 엔진이 읽게 할지 — 엔진 담당. 켜지 않으면 해커톤 제출물에 Strands가 코드로만
존재하고 데모에는 안 나온다.

**7. 결과 화면 에이전트 — 완료, 기본 꺼짐 (2026-09-14).**
`src/agent/result_agent.py` + `recommendation_service.handle_result_message` 분기 + `tests/test_result_agent.py`(6건).
`RESULT_AGENT=1`. 도구 6개가 `list_alternatives`·`swap_item`·`patch_item`·`review_service.get_summary` 를 감싼다.
같이 고친 것: 교체 뒤 reason 이 pending 으로 남던 것(`swap_item` 이 교체 기록 문장을 적음).
같은 날 (A) 추천 요약을 summary 문단으로(`ExplanationDraft.summary`, [5] 입력에 사용자 조건, extra 안내는 코드가),
(C-1) `checks` 를 코드로 조립(검증 쟁점·리뷰 관측·교체 표시) — 전엔 pending 하드코딩이라 프론트가 무한 폴링했다.
`EXPLAIN_SYSTEM` 규칙 8 추가·금지어 3개 추가는 03 담당(사용자) 판단으로 — sllm 담당자에게 알릴 것.
남은 것: 교체 뒤 요약 재생성(지금은 ※ 주석), 리뷰 관측 문장 길이(프론트) — `docs/결과화면_에이전트_strands.md`.

들어가기 전 참고: `tests/test_list_service.py` 3건은 **`origin/develop` 원본에서도 같은 줄에서 실패한다**(임시 워크트리로 대조 확인함). 우리 변경 탓이 아니고 develop 담당자 몫이다.
