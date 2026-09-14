# 팀 공지 — LLM 연동 작업 중 다른 브랜치 파일에 생긴 변화 둘

**날짜:** 2026-09-13. sllm 브랜치([3-C]·[5] LLM 담당) 작업 중 develop·전체 계약에 영향 있는
부분을 정리했다.

## 1. `recommendation_service.py`의 검증 메시지 소스 변경 (develop 담당자용)

커밋 `1c76d94`([3-C] 쟁점 문장화 LLM 연결)에서 `add_validation` 호출의 `message` 인자를 바꿨다.

```diff
- threshold={}, message=issue.judge or issue.axis,
+ threshold={}, message=issue.text or issue.judge or issue.axis,
```

**이유:** `issue.text`는 [3-C]가 LLM(또는 규칙 템플릿 fallback)으로 생성하는 중립 서술
문장이다("전력 여유: 관측값 상시부하 420W · 정격 대비 55%" 같은). 이게 없으면
`validation_result.message`엔 `judge`("경미"·"위반" 같은 한 단어)나 `axis`(축 이름)만
남아서, 검증 쟁점이 왜 그런지 사용자에게 설명이 안 된다. `issue.text`가 항상 채워지므로
(LLM 실패해도 규칙 템플릿으로 내려감, §10-11 E4) 순서상 최우선으로 뒀다.

**영향받는 곳:** `get_stored_result`의 `verification.issues[].text`가 이 `message` 컬럼을
그대로 노출한다([recommendation_service.py](../src/services/recommendation_service.py) 검색:
`"text": v["message"]`). 이 파일을 다시 손보실 때 이 의존관계를 참고해 주시면 됩니다.

## 2. 계약 문서 §D-3이 아직 Bedrock 기준 (전체 공지)

`src/CLAUDE.md`에 명시된 결정: **"Bedrock은 쓰지 않는다. OpenAI만 쓴다" (2026-09-13).**
[3-C] 쟁점 문장·[5] 설명 문장은 이제 `LLM_PROVIDER=openai`로 실제 OpenAI를 호출한다
(`.env.example`도 이번에 이 결정에 맞춰 정리했다 — `EMBEDDING_MODEL`/`LLM_REGION`은
RAG(임베딩) 쪽 변수라 비워 두고, Bedrock 기본값과 안 겹치게 주석을 추가했다).

**그런데 계약 문서 §D-3**(`docs/frontend_외부수정요청.md` — 이 브랜치엔 파일이 삭제돼 없고
`origin/develop`·`origin/front`에 있음)은 **아직 Bedrock Claude Haiku 기준으로 적혀 있다.**
기획서·계약 문서를 근거로 새 작업을 시작하시는 분은 이 문서 쪽이 아직 갱신 전이라는 점을
참고해 주세요. LLM 사용 범위 자체(어디에 LLM을 쓰는지: [1] 미사용·[3-C]/[5] 사용)는
안 바뀌었고, **벤더만** Bedrock → OpenAI로 바뀐 것이다.

문서 갱신은 `src/CLAUDE.md`의 "문서 갱신 의무" 절대로 프론트 담당자와 합의 후
계약 문서에 반영하는 절차를 따라야 한다 — sllm 쪽에서 임의로 그 문서를 고치지 않는다.
