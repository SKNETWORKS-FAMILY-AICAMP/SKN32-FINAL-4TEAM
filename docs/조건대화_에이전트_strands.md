# 조건 대화 에이전트 — Strands Agents SDK 스파이크 (2026-09-14)

## 왜

- *Agents for Humans* 해커톤은 "**Strands Agents SDK 로 만든** 에이전트"를 제출 대상으로 정의한다.
  9/14 아침 기준 코드·의존성 어디에도 Strands 가 없었다.
- 9/13 회의 두 건에서 "에이전트로 나갔는데 에이전트가 안 보인다", "추가 조건·변경 요청 자유입력이
  결과에 반영 안 된다"가 같이 나왔다. 조건 대화의 자유 텍스트는 규칙 추출(`src/engine/slot_rules.py`)이
  키워드만 잡아서, "흰색 케이스면 좋겠어요" 같은 말은 어디에도 남지 않았다.

둘을 한 번에 푸는 최소 범위가 **조건 대화(`POST /session/{id}/message`)를 Strands 에이전트로**다.
추천 엔진([2]~[5])은 손대지 않았다.

## 무엇

`src/agent/conditions_agent.py`. Strands `Agent` 하나에 도구 셋:

| 도구 | 하는 일 |
|---|---|
| `set_condition(field, value)` | `slot_schema` 필드 하나 설정. enum·int·bool·list·nullable 을 **코드가** 검사하고, 틀리면 "오류: …" 를 돌려줘 모델이 고쳐 부른다 |
| `add_extra_condition(text)` | 필드에 없는 요구("흰색 케이스", "RGB 없이")를 `extra` 목록에 기록 |
| `clear_condition(field)` | 취소 |

도구 결과 꼬리에 **규칙이 계산한 "남은 필수 항목 · 다음 질문"** 을 실어 보낸다. 그래서 모델이 무엇을
물을지 정하지 않는다 — `session_service.compute_missing`·`_next_question` 이 정하고, 화면의 질문 칩과
답변 문장이 같은 항목을 가리킨다.

경계 (§D-3 "판정·수치는 코드, LLM 은 서술" 그대로):

- 에이전트는 DB 를 안 만진다. 도구는 `ConditionDraft.patches` 에 모으고 `session_service.handle_message` 가
  규칙 경로와 같은 `upsert_condition(origin="extracted")` 로 적는다. API 응답(`ConditionState`)은 안 바뀐다.
- 모델 호출이 실패하면 **그 턴만** 규칙 추출로 처리하고 `WARNING` 로그를 남긴다. 화면에서는 구분되지 않는다.
- 답변 언어는 사용자의 마지막 메시지에서 코드가 판별해(한글 유무) 프롬프트 마지막 줄에 박는다.
  프롬프트가 한국어라 "사용자 언어로" 라는 규칙만으로는 영어 입력에도 한국어로 답했다.

## 켜는 법

```
MOCK_MODE=0
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini        # 실측에 쓴 모델
OPENAI_API_KEY=...
CONDITIONS_AGENT=1
```

**기본은 꺼짐(`CONDITIONS_AGENT=0`).** 계약 §D-3("[1] 조건 추출은 규칙 기반, 프론트와 합의")이 아직
유효하고 프론트 담당자 합의를 받지 않았다. 합의되면 `src/config.py` 의 기본값 한 글자를 바꾼다.
프론트 쪽 변경은 없다 — 질문 칩·`next_question`·`can_recommend` 계약이 그대로다.

의존성: `strands-agents[openai]` (`pyproject.toml`·`requirements.txt`). Bedrock 은 안 쓴다(9/13 결정) —
Strands 의 OpenAI 모델 공급자를 쓰므로 기존 `OPENAI_API_KEY` 그대로다.

## 실측 (gpt-4o-mini, 2026-09-14)

컴퓨터, 한국어 — 턴당 2~3초:

| 입력 | 도구 호출 | 답변 |
|---|---|---|
| 발로란트랑 롤 위주로 할 게임용 PC 맞추려고요. 예산은 150만원 정도 | purpose=game · games=[발로란트, 롤] · budget_max=1500000 | …예산은 150만원으로 설정했습니다. 이제 가장 중요하게 생각하시는 건 무엇인가요? |
| 가성비요. 그리고 케이스는 흰색이었으면 좋겠고 RGB는 없었으면 해요 | priority=value · extra+=["케이스는 흰색, RGB 없음"] | …이 조건으로 추천을 받아볼 수 있습니다 |
| 아 예산 180만원까지는 괜찮아요. QHD 165Hz 모니터 쓸 거예요 | budget_max=1800000 · resolution=QHD_165 | 예산을 180만원으로 조정하셨고, 목표 해상도를 QHD 165Hz로… |

컴퓨터, 영어 — 답변도 영어:

| 입력 | 도구 호출 |
|---|---|
| I need a PC for video editing and some 3D rendering. Budget around 2.5 million won. | purpose=creation · budget_max=2500000 → "What is your priority: performance, value, or quiet?" |
| Performance matters most. Oh, and I'd like it to be as quiet as reasonably possible — but performance first. | priority=performance · noise_sensitive=true |
| Actually make the budget 3,000,000. | budget_max=3000000 |

유아용품 — 질문 칩의 라벨→값 매핑(출산 예정→0, "특이사항 없음"→none)을 프롬프트에 넣은 뒤:

| 입력 | 도구 호출 |
|---|---|
| 출산 예정이에요. 수유랑 수면 쪽 물품 위주로 준비하려고요 | age_months=0 · needs=[수유, 수면] |
| 피부 특이사항은 없고, 아직 가진 건 하나도 없어요. 예산은 50만원 | health_skin=[none] · owned_items=[none] · budget_max=500000 |

HTTP 완주 (PGlite 테스트 DB, `CONDITIONS_AGENT=1`): `POST /session` → `/category`(computer/build) →
`/message` 2턴 → `can_recommend=true` → `POST /recommend` 202 → `GET /result` done, 8슬롯 1,457,000원
(예산 1,500,000). 조건 패널에 `purpose·budget_max·priority` 가 규칙 경로와 같은 형식으로 나온다.

### 고치면서 안 통한 것

- 첫 버전은 턴 시작 시점의 "다음 질문" 을 프롬프트에 고정했다 → purpose 를 방금 채워 놓고 purpose 를 또 물었다.
  도구 결과에 다시 계산한 다음 질문을 실어 해결.
- "사용자 언어로 답하라" 규칙만으로는 영어 입력에 한국어로 답했다(프롬프트·이력이 한국어). 코드 판별로 해결.
- 게임 제목을 `games` 가 아니라 `extra` 에 넣었다. 필드 설명에 "(항목 여러 개)"와 규칙 2("필드가 있으면 그 필드에")를
  추가하고 나서 `games` 로 갔다.
- 목록 분리에 `·` 를 넣었더니 선택지 라벨 "이유식·식사" 가 둘로 쪼개졌다. 쉼표만 분리.
- "3,000,000." 처럼 단위 없는 금액은 `_parse_won` 이 못 잡아 오류→clear 로 흘렀다. `_parse_amount` 로 확장.

## 한계 · 남은 것

- **`extra` 는 조건 패널에만 남고 엔진([2]~[5])이 읽지 않는다.** "흰색 케이스" 가 후보 필터나 설명에 반영되려면
  엔진 담당의 작업이 필요하다. 지금은 "기록되고 보인다" 까지다.
- 규칙 추출 대비 턴당 2~3초·토큰 비용. 데모·리허설에서 켤지는 팀이 정한다.
- 실패 시 규칙 경로로 조용히 내려간다(로그만). 데모 중 답변이 갑자기 "죄송해요, 이해하지 못했어요" 로 바뀌면 그 경우다.
- 모델 호출이 있는 턴은 자동 테스트에 없다. `tests/test_conditions_agent.py` 는 값 검사·다음 질문·이력·Strands 등록만 본다.
- 도구 호출 기록(`TurnResult.trace`)은 로그에만 간다. "추천 과정 보기" 에 조건 수집 과정으로 붙일 수 있다.

## 같이 발견한 것 (이 작업과 무관, 담당자에게)

- `db/seed.py` 가 `shared.unit` 에 INSERT 하는데 마이그레이션 0012 가 그 테이블을 지웠다. **새 DB 에서
  `db/setup_all.py` 가 2단계에서 멈춘다.** 이미 시드된 DB 에서는 안 보인다.
- 같은 조건으로 두 번 돌렸을 때 [5] 설명 문장이 한 번은 LLM 문장, 한 번은 규칙 템플릿("순위 1위이고 밸런스에
  부합하여…" ×8)이었다. DB 경로는 `stage5_explain.run` 에 `noop` 로그를 넘겨서 왜 떨어졌는지 남지 않는다.
- LLM 이 쓴 reason 에 "우수한 평가" 가 나왔다 — `EXPLAIN_SYSTEM` 규칙 7의 평가어 목록 밖 단어.
- 결과 화면 caveats 에 `리뷰 진위 (담당 팀원)`·`RAG 근거 (담당 팀원)` 자리표시 문자열이 그대로 나간다
  (`src/engine/stage3c_verify.py:125`).

## 영어 데모 대비 (2026-09-14 오후)

데모는 영어로 진행한다. 저장·계산은 그대로 두고, 사용자에게 나가는 것만 언어·통화를 따른다.

- **달러 입력** — "$1,200", "1500 dollars", "1.2k USD" 를 `_parse_money` 가 고정 환율(`USD_KRW_RATE`, 기본 1,400원)로
  원화 환산해 `budget_max` 에 저장하고, 조건 `currency=USD` 를 남긴다. 도구 결과·프롬프트·조건 패널(`session_service._display`)
  ·03 에이전트(`result_agent._won`)·요약 캐비앗은 **달러 먼저, 원화 괄호**("$1,200 (1,680,000원)"). 달러 얘기가 없으면 전과 같다.
  실시간 환율이 아니라는 것을 `.env.example` 에 적었다.
- **언어 조건** — 02 가 마지막 메시지의 글자로 판별한 언어를 조건 `language=en|ko` 로 남긴다(패널엔 안 보임).
  `[3-C]`·`[5]` 는 호출 시점에 `lang.localize_system` 으로 "한국어 존댓말" 규칙 줄을 영어로 바꿔 끼우고 영어 지시를 붙인다
  (문안 파일은 그대로). 코드가 만드는 문장(구매 전 확인·교체 기록·요약 폴백·캐비앗·메모)은 `L(lang, ko, en)` 로 갈린다.
  조건 패널 표시값은 yaml `display_en`("Gaming", "Value for money"). 리뷰 관측 문장은 데이터라 한국어 그대로.
- 안 통한 것: (1) `[3-C]` 는 영어 지시를 뒤에 붙여도 규칙 5 "한국어 존댓말" 을 따랐다 → 그 줄을 바꿔 끼워야 했다.
  (2) `[5]` 영어 초안은 "excellent"·"the best"·"score" 로 매번 통째로 버려졌다 → 금지어에 영어를 넣고, reason 은
  **슬롯별로만** 걸러 그 슬롯만 템플릿으로(헤드라인·요약은 여전히 전체 재시도). (3) 영어 문맥에선 게임 제목을
  `extra` 에 넣었다 → 도구 docstring 에 영어 한 줄("Game titles go to games").
