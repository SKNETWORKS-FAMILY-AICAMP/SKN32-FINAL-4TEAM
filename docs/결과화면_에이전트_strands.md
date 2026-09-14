# 결과 화면 대화 에이전트 — Strands Agents SDK (2026-09-14)

03 추천 결과 화면 아래 입력칸(`POST /session/{id}/result-message`)의 자유 텍스트를 처리한다.
02 조건 대화 에이전트([[조건대화_에이전트_strands.md]])와 같은 뼈대다.

## 왜

기존 경로(`recommendation_service.handle_result_message`)는 **LLM 없이** 정규식이었다 — 슬롯 동의어 + "저렴/좋은"
단어를 찾아 카탈로그 최저가/최고가 후보로 바꾸고, 그 외("왜 이 CPU야?", "케이스는 나중에 살게")는 전부
"이해하지 못했어요". 결과 화면은 사용자가 구성표를 놓고 **행동**(교체·빼기·수량·시점)과 **질문**(근거)을 섞어
말하는 곳이라, 무엇을 부를지 고르는 루프가 필요하다. 이 프로젝트에서 Strands 가 가장 맞는 자리다.

## 무엇

`src/agent/result_agent.py`. Strands `Agent` + 도구 6개 — 전부 **이미 있던 서비스 함수**를 감싼다.

| 도구 | 감싸는 것 | 사용자 말 |
|---|---|---|
| `list_alternatives(slot)` | `list_alternatives` — 가격순 후보, `candidate_id`, 가격 차, 성능 티어. 요구 성능 티어(`planning.requirement.match_spec.perf_tier_min`)보다 낮으면 **⚠ 요구 사양 미달** 표시 | "그래픽카드 다른 거 뭐 있어?" |
| `swap(slot, candidate_id)` | `swap_item` | "더 싼 걸로" → 목록 조회 후 선택 → 교체 |
| `set_timing(slot, timing)` | `patch_item(timing=)` | "케이스는 나중에 살게" |
| `set_qty(slot, qty)` | `patch_item(qty=)` | "SSD 2개로" |
| `remove_or_restore(slot, keep)` | `patch_item(selected=)` | "쿨러 빼줘" / "다시 담아줘" |
| `explain(slot)` | 저장된 추천 이유 + 예산 비중 + 세트 검증 쟁점 + 리뷰 관측(`review_service.get_summary`) | "왜 이 CPU야?" |

시스템 프롬프트에 매 턴 **구성표**(슬롯·부품·가격·수량·시점·빼둠·저장된 추천 이유)·총액·예산 잔여·검증
신뢰도·쟁점을 넣는다. 도구 결과는 바뀐 뒤의 총액·예산 잔여·"예산 초과"·"호환·검증은 재실행되지 않음"을 실어
모델이 그대로 말하게 한다.

경계:

- **판정 금지** — 부품의 좋고 나쁨, 리뷰 진위(결정 0001), 호환 여부를 에이전트가 정하지 않는다. `explain` 은
  저장된 사실만 옮기고, 프롬프트가 "호환에 대해 '문제 없다'고 단정하지 않는다"를 명시한다.
- **교체 뒤 호환·검증은 재실행되지 않는다.** 엔진의 `link_check` 가 고정값(`stage4_optimize.py:71`)이라 코드도
  못 한다. 도구 결과에 그 사실을 적고, 재계산은 화면의 "다른 구성 보기"로 안내한다.
- 도구는 순차 실행(`SequentialToolExecutor`) — 요청 스레드의 psycopg 연결 하나를 같이 쓴다.
- 대화 이력은 **프로세스 메모리**(run_id 별 최근 8턴). 결과 화면 채팅은 서버에 저장되지 않는 계약이라 재시작하면
  사라진다. "두 번째 걸로" 같은 이어 말하기는 이 이력으로 통한다.
- 응답 계약 `{reply, result}` 그대로 → 프론트 수정 없음.
- 실패 처리: 도구가 아무것도 안 바꾼 채 실패하면 규칙 경로로(DB 오류면 `rollback` 먼저). 도구가 이미 구성표를
  바꾼 뒤 모델이 실패하면 규칙 경로로 넘기지 않고(또 바꿀 수 있다) 적용된 변경 목록을 답으로 낸다.

## 켜는 법

```
RESULT_AGENT=1        # + MOCK_MODE=0 · LLM_PROVIDER=openai · LLM_MODEL · OPENAI_API_KEY
```

기본 꺼짐. 02 의 `CONDITIONS_AGENT` 와 독립이다.

## 실측 (gpt-4o-mini, docker DB, 2026-09-14)

초기 구성 8슬롯 1,457,000원 / 예산 1,500,000원.

| 입력 | 도구 호출 | 답변 | 초 |
|---|---|---|---|
| 그래픽카드 좀 더 싼 걸로 바꿔줘 | `list_alternatives(GPU)` | 더 싼 후보 없음 — RX 7600 이 가장 저렴 (사실) | 2.3 |
| 왜 이 CPU야? | 선조회 `explain(CPU)` | 성능 티어 6, 예산 비중 18%, 저장된 이유, 검증 쟁점 [power] | 3.3 |
| 케이스는 나중에 살게. 그리고 SSD는 2개로 | `set_timing(케이스, later)` · `set_qty(저장장치, 2)` | 총액 1,550,000원, **예산 50,000원 초과** 언급 | 2.8 |
| 지금 예산 안에 들어와? | (없음) | 초과 50,000원, SSD 2개 때문 | 0.9 |
| Put the GPU back to something one step better and tell me what changed. | `list_alternatives` → `swap` | 영어로: RX 7600 → 다음 가격대 GPU, 총액·초과액, "compatibility and verification have not been re-evaluated" | 2.9 |
| 처음부터 다시 짜줘 | (없음) | 도구 없음 — "다른 구성 보기" 안내 | 1.0 |

같은 요청을 규칙 경로에 넣으면: "왜 이 CPU야?" → "CPU를 어떻게 바꿔드릴까요?", "케이스는 나중에 살게" → "이해하지 못했어요".

### 고치면서 안 통한 것

- **`set_item(slot, selected, qty, timing)` 하나로 두면** gpt-4o-mini 가 "케이스는 나중에 살게"를 `selected=false` 로,
  "SSD 2개"에 `timing=later` 를 섞어 넣었다. docstring 을 아무리 명시해도 반복됐다. **단일 목적 도구 셋으로 쪼개니** 바로 맞았다.
- **"왜 이 CPU야?"에 모델이 `explain` 을 안 부르고** "확인할 수 없습니다"라고 답했다(두 번 연속). 규칙 문장을 강하게
  써도 같았다. 그래서 근거 질문("왜·이유·근거·괜찮·믿을·어때·리뷰·why·reason·review")은 **코드가 먼저 `explain` 을
  돌려 프롬프트에 싣는다**(`_prefetch_explanations`). 슬롯을 못 찾으면 담긴 부품 전부. 도구도 남겨 둬 후속 질문에 쓴다.
- 첫 답변에 "호환성 문제는 없습니다"가 나왔다 — 알 수 없는 것을 단정. 규칙 5에 금지 문장을 추가.

## 같이 고친 것 (에이전트와 무관하게 화면에 보이던 것)

- **후보 교체 뒤 "추천 이유"가 영원히 "정리하는 중…"** — `update_candidate_variant` 가 reason 을 `pending` 으로
  되돌리는데 다시 채우는 경로가 없었다. `[5]` 를 다시 돌릴 수는 없어서(rank·build 가 메모리에만 있었다) `swap_item` 이
  코드가 아는 사실로 한 줄 적는다: "사용자 요청으로 교체한 부품입니다 — 자동 추천은 'X'(가격)였고 이 후보는 ±N원입니다.
  순위·검증 점수는 교체 전 구성 기준입니다." 규칙 경로의 교체도 `swap_item` 을 거치게 바꿨다.
- `engine_repo.get_candidate_evidence` 는 0012 가 지운 `engine.candidate_evidence` 를 읽는 옛 코드다 — 부르면
  트랜잭션이 깨진다. 여기서는 안 부른다.

## 한계 · 남은 것

- **교체 뒤 요약(`explanation`)은 옛 구성 기준으로 남는다.** 03 요약 고도화(A)에서 다룰 것 — 도구가 구성을 바꾸면
  `explanation.status=pending` 으로 두고 다시 만드는 경로가 필요하다.
- `checks`("구매 전 확인")는 여전히 코드에 `pending` 하드코딩(`recommendation_service.py`). C 작업.
- 이력이 프로세스 메모리라 uvicorn 워커가 둘 이상이면 턴마다 다른 워커에 갈 수 있다. 데모는 워커 1개.
- 모델 호출이 있는 턴은 자동 테스트에 없다. `tests/test_result_agent.py` 는 슬롯 찾기·인자 검사·선조회 트리거·
  프롬프트 내용·Strands 등록만 본다.
