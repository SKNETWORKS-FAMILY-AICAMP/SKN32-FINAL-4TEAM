# 팀 공지 — `get_stored_result` failed 상태 누락 수정

**받는 사람:** develop 담당자 (`3e2a7ee` 작성자).
**날짜:** 2026-09-13.

`3e2a7ee`(부품표를 [5] 설명 문장보다 먼저 done 처리) 잘 받았습니다 — 요청대로 정확히
반영돼 있었습니다. 머지해서 리뷰하다가 `get_stored_result`에서 버그 하나를 발견해서
바로 고쳤습니다(제 브랜치 `sllm`, 커밋 `6e0bec1`).

## 무엇이 문제였나

`3e2a7ee`가 실패 시 `reason_status`/`explanation_status`를 `'failed'`로 정확히
남기는데, `get_stored_result`([recommendation_service.py:303](../src/services/recommendation_service.py#L303),
[:328-330](../src/services/recommendation_service.py#L328-L330))는 각각:

```python
"reason": {"status": "ready", "text": row["reason"]} if row["reason"] else {"status": "pending", "text": None},
...
"status": "ready" if run.get("explanation_status") == "ready" else "pending",
```

즉 **"ready가 아니면 무조건 pending"**으로만 매핑하고 있어서, DB에 실제로 `failed`가
들어가도 API 응답은 계속 `pending`으로 나갑니다. 프론트는 `pending`이면 폴링을
계속하도록 돼 있으니, [5]가 진짜로 실패하면 **사용자가 영원히 로딩 화면을 보게
됩니다** — 이번에 없애려던 무한 로딩이 다른 경로로 재발하는 셈이라 바로 고쳤습니다.

## 무엇을 고쳤나

컬럼값을 그대로 내보내도록 2줄만 바꿨습니다 (DB 제약은 `db/migrations/0008_frontend_contract.sql`에서
처음부터 `pending`/`ready`/`failed` 세 상태를 다 지원하고 있었습니다):

```python
"reason": {"status": row["reason_status"], "text": row["reason"]},
...
"status": run.get("explanation_status") or "pending",
```

## 확인 못 한 것

이 환경엔 `psycopg`도 로컬 Postgres도 없어서, 두 트랜잭션 분리가 실제로 의도대로
동작하는지(부품표가 [5] 완료 전에 실제로 조회되는지)는 **코드 리딩으로만 확인**했고
DB로 직접 검증은 못 했습니다. `pytest`는 기존 기준선(87 passed, `test_list_service.py`
3건은 기존부터 실패하던 것이라 제외) 그대로였습니다. 실제 DB로 한 번 같이 확인하면
좋겠습니다.
