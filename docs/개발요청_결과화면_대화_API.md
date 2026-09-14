# 개발 요청 — 추천 결과 화면의 대화·후보 교체 API 미구현

**요청 대상:** develop 소유 파일(`src/routers/session.py`, `src/services/session_service.py`).
**요청자:** 프론트 담당자, 확인일 2026-09-14.

## 재현

추천 결과 화면(3단계) 하단 "추천 결과에 대해 더 물어보세요"에 텍스트를 입력하고 전송하면
"서버 기능이 아직 준비 중이에요."가 뜬다.

**원인:** 프론트([results.js](../frontend/js/pages/results.js), `TF_PLAN.resultMessage` →
[core.js:35](../frontend/js/core.js#L35))가 `POST /session/{id}/result-message`를 호출하는데,
`src/routers/session.py`에 이 라우트가 **아예 없다.** FastAPI가 404를 반환하고, 프론트 공통
에러 처리(`api.js`)가 404/501/405를 전부 "서버 기능이 아직 준비 중이에요"로 뭉뚱그려 보여준다
(버그가 아니라 미구현 상태를 정확히 반영한 메시지):

```js
// frontend/js/api.js
if(response.status===501||response.status===404||response.status===405)
  throw new TF_ApiError(response.status,'not_ready','서버 기능이 아직 준비 중이에요.');
```

## 필요한 것 — `POST /session/{list_id}/result-message`

| 요청 본문 | 성공 응답 | 주요 오류 |
|---|---|---|
| `{"text"}` (300자 이하) | `200 {"reply", "result": RecommendResult}` | `validation_failed`(422) |

- `reply`: 사용자 요청에 대한 짧은 응답 문장 (예: "그래픽카드를 더 저렴한 걸로 바꿨어요.")
- `result`: 요청이 반영된 최신 `RecommendResult` — `GET /session/{id}/result`와 **완전히 같은 모양**
  (이미 `get_stored_result`가 조립하는 그 스키마 그대로)
- **규칙 기반 해석, LLM 미사용** — "그래픽카드를 더 저렴한 걸로" 같은 문장을 슬롯+방향으로
  파싱해 후보 교체로 연결하는 것으로 보인다. [3-C]/[5]와 달리 sllm 쪽 LLM 스코프가 아니다.

## 참고 — 같이 빠져 있는 나머지 넷

같은 "결과 화면" 기능 묶음에서 아래 넷도 `session.py`에 라우트가 없다(Swagger `/docs`에서
직접 확인, 2026-09-14 기준). 지금 당장 사용자가 건드린 건 `result-message`뿐이지만, 같은
화면의 버튼들(수량 ±, 담기/빼기, 후보 교체)이 순서대로 다 걸릴 것으로 예상되어 같이 적는다.

| 화면 동작 | 메서드·경로 | 요청 본문 | 성공 응답 |
|---|---|---|---|
| 장바구니 담기·빼기, 수량, 구매 시점 | `PATCH /session/{list_id}/items/{item_id}` | `{"selected"?, "qty"? (1~99), "timing"? ("now"\|"soon"\|"later")}` | `200 RecommendResult` |
| 후보 교체 창 | `GET /session/{list_id}/items/{item_id}/alternatives` | — | `200 {"items": [Alternative]}` |
| 후보 선택 | `POST /session/{list_id}/items/{item_id}/swap` | `{"candidate_id"}` | `200 RecommendResult` |
| 사양 파일 인식(업그레이드 모드) | `POST /session/{list_id}/spec-file` | — | (미확정) |

`Alternative` 모양:
```json
{"candidate_id": "uuid", "label": "절약형 후보", "current": false,
 "product": {"product_key": "rtx-3060", "name": "GeForce RTX 3060 12GB", "brand": "NVIDIA", "spec_summary": "12GB GDDR6", "image_url": null},
 "price": 290000, "price_delta": -40000, "review": {"total_count": 932, "excluded_ratio": 0.09, "rating_refined": 4.4}}
```

이 다섯 개는 과거 `docs/frontend_외부수정요청.md`(§D-4-2, 2026-09-11 작성)에 이미 정리돼
있던 내용과 같다. 그 파일 자체는 최근에 삭제됐지만(다른 브랜치에서도 삭제 예정 — 낡은 계약
문서를 유지보수하기보다 새로 필요할 때마다 이런 식으로 짧게 요청하는 쪽으로 정리하는 것으로
이해했다), API 모양 자체는 여전히 유효해 보여 그대로 인용했다. 다르게 가고 싶은 부분 있으면
알려달라.

## 확인 요청 사항

1. `result-message` 먼저 반영 가능한지 (지금 바로 막힌 것).
2. 나머지 넷도 같이 반영할지, 우선순위를 어떻게 둘지.
3. `result-message`의 "규칙 기반 해석" 범위 — 어떤 패턴까지 지원할지(예: 슬롯 교체만 vs
   예산 조정 같은 것도) 프론트 쪽과 맞춰야 하면 알려달라.
