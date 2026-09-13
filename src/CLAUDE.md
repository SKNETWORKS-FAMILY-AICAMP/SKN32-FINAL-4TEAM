# LLM 연동 작업 지침 (`sllm` 브랜치)

## 이 문서의 범위

이 문서는 **LLM 연동에 해당하는 파일만** 다룬다. `src/` 전체에 대한 지침이 아니다.

| 파일 | 역할 |
|---|---|
| `src/clients/llm_client.py` | LLM API 호출 래퍼 (`call_llm`) |
| `src/engine/prompts.py` | 시스템 프롬프트 문안 |
| `src/engine/stage3c_verify.py` | [3-C] 검증 쟁점 문장 |
| `src/engine/stage5_explain.py` | [5] 추천 설명 문장 |
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

- 작업 브랜치는 `sllm`이다. 원래 README만 있는 독립 히스토리였고, 2026-09-13에 `front`를 병합해(`--allow-unrelated-histories`) 최신 코드를 받았다.
- **git commit·push·branch 변경은 사용자가 요청할 때만 한다.**
