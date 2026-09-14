# develop ← rag 병합 검증 (2026-09-13)

결론: 충돌 마커는 해결됐지만 실행 호환성은 깨져 있어 정상 병합으로 판단할 수 없다. 이번 요청에서는 검증만 수행했으며 구현 수정·병합 커밋·서비스 DB 변경은 하지 않았다.

## 실측

- `uv lock --check --offline`: 통과(47 packages). pyproject/lock 일관성 확인.
- 전용 빈 DB `merge_review_20260913`에 `db/setup_all.py`: 실패. develop에 있는 `0011_drop_rag_schema.sql`이 rag 스키마를 제거하고, rag 브랜치에서 들어온 `0012_schema_reduction_destructive.sql`이 그 스키마를 사용하여 `schema "rag" does not exist`로 실패한다. 단계 일부가 진행됐다는 로그를 전체 설치 성공으로 해석하면 안 된다.
- 전체 pytest(검증 DB 환경변수 지정): 테스트 수집 중 `tests/test_baby_verification.py:30`의 `persist_candidate_check` import 실패로 종료2. 테스트 실행 통과 수는 없다. pandas 미설치 관련2개 모듈 스킵. 실패는 DB 실행 이전 import 문제다.
- DB에 의존하지 않는 optimizer/db_pipeline/pipeline_smoke/p1234_review_fixes만 별도 실행: **42 passed, 2 skipped**, 0.54초. 이2개 스킵은 의도적으로 DB 환경변수를 제거한 실행에서 DB fixture가 필요한 신규 회귀 사례다. 전체 API 통과 의미는 아니다.
- 자동 설치 실패 뒤 시도한 유아 시드도 실패했다. 불완전 DB에서 발생한 후속 실패이므로 독립적인 카탈로그 회귀로 판정하지 않는다.

## 우선 해결 대상

1. DB 아키텍처 병합: develop의 rag 삭제와 rag 브랜치의 pgvector 유지 전제를 하나로 정리해야 한다. 단순 충돌 구간 우선 선택으로 해결할 수 없는 비충돌 파일 사이의 의미 충돌이다.
2. `src/repo/engine_repo.py`에서 사라진 `persist_candidate_check`와 P3 호출자·테스트 계약을 복원/통합해야 한다.
3. `PlanRepo.add_purchase_line/list_purchase_lines`(150/161행)는 존재하지만 삭제 대상인 planning.purchase_line을 직접 사용한다. 축소 DB의 planning.item 저장·조회로 통합해야 한다. 정적 SQL 확인이며 설치가 막혀 목록 HTTP 재현은 하지 못했다.

위 문제를 해결한 뒤 새 빈 DB에서 설치와 전체 테스트를 다시 수행해야 한다. 정상 통과한 순수 로직42개는 해당 파일 추가 변경이 없으면 반복할 필요가 없다.

로그: [설치](artifacts/merge-setup-2026-09-13.log), [전체 테스트 수집](artifacts/merge-pytest-2026-09-13.log), [순수 로직](artifacts/merge-pure-tests-2026-09-13.log).
