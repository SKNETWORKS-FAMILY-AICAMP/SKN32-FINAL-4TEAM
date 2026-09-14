# Baby 운영 결정 기록 — v3

기준일: 2026-09-14. 이 기록은 develop `da79839`과 ACTIVE DB CONTRACT의 현재 운영 범위만
명시한다. 과거의 PostgreSQL `rag`/pgvector 경로나 완전 축소 SQL을 운영 대상으로 복원하지 않는다.

| 범위 | 상태 | 근거/입력 |
|---|---|---|
| O1 develop DB 준비성 | 구현 | 0000–0013 체인, `rag`/`dataset` 부재, baby domain hash, 시드 후보·가격·단위, API/실행 상태를 읽기 전용 CLI가 검사한다. |
| 검색 provider 경계 | partial | `SearchProvider`와 `local-file` 개발 provider가 있다. 미설정은 unknown/자동선택 불가이며 DB `rag` fallback은 없다. |
| O2 실제 자료/모델 평가 | blocked | 승인된 실제 자료, 평가 기준, 모델·리전·자격증명이 제공되지 않았다. synthetic 또는 local-file 결과를 실제 모델 평가로 부르지 않는다. |
| O3 업로드/OCR/비동기 적재 | not_selected | 파일 형식·크기·저장소·운영 runtime 범위가 선택되지 않았다. |
| O4 별도 벡터 DB | not_selected | 제품, 접근 정책, 보존 정책의 명시적 결정이 없다. 현재 DB에는 `rag` schema가 없어야 한다. |
| O5 배포/모니터링 | not_selected | 호스팅 대상, 환경, 비밀값, publish 권한이 없다. |
| 가격 알림 | excluded | develop의 `notification.price_watch`는 보존하지만 유아 발송 기능을 새로 활성화하지 않는다. |

## 안전한 로컬 리허설

기존 서비스 DB를 초기화하지 않는다. 이름이 확인된 빈 일회용 DB에만 다음 순서로 실행한다.

```bash
export DATABASE_URL='postgresql://truefit:truefit@127.0.0.1:5432/<disposable>?sslmode=disable'
uv run python db/setup_all.py
uv run python scripts/seed_baby_catalog.py --corpus synthetic --dataset-version baby-demo-v1
uv run python scripts/check_baby_readiness.py --corpus synthetic --provider unconfigured --output generated/operations/readiness.json
uv run python -m pytest -q tests/test_baby_readiness.py tests/test_schema_reduction.py tests/test_baby_session_http.py tests/test_baby_recommendation_http.py
```

`partial` readiness is expected if provider 또는 게시된 설명서 매핑이 없다. 그것은 DB 설치 실패가
아니며, 외부 검색/실제 운영 준비 완료 선언도 아니다. provider publish/search/revoke와 철회 후
DB 근거 재검사는 P3의 실제 backend 게이트가 선택된 경우 별도로 수행한다.

## 재시작·부하 경계

현재 추천 worker는 in-process `BackgroundTasks`다. 프로세스 종료 뒤 `running` 실행을 복구하는
내구 큐가 아직 없으므로, 재시작 복원 검증은 미충족이다. 선택된 실제 배포 환경이 생기면 단일
동시성에서 create→conditions→recommend→GET result→confirm/report를 먼저 측정하고, 이후
동시성 1/2/4에서 오류율·p50/p95·DB pool 상태를 기록한다. 이 문서는 처리량 수치를 주장하지 않는다.
