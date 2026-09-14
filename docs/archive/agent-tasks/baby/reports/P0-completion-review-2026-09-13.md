# P0 완료 검토 — 2026-09-13, d96ccd2 + 현재 작업 트리

> 후속 상태: 이 문서는 수정 전 재현 기록이다. 두 결함은 이후 수정됐으며 [수정 보고서](P0-fixes-2026-09-13.md)에 신규 회귀 테스트·적용 절차를 기록했다.

판정: **partial_rework_required — 완료 승인 불가.** 기존 구현을 재사용하며 아래 두 결함을 보완한다. P1/P2의 독립 작업은 계속할 수 있지만 P0 완료를 전제로 한 통합 승인은 보류한다.

## 완료를 막는 결함

| 우선순위 | 근거 및 실제 결과 | 미충족 기준 | 필요한 보완 |
|---|---|---|---|
| 높음 | `src/services/list_service.py:16,46`이 삭제된 `config.domain_version`을 조회한다. 세션 생성·baby 선택은200이나 같은 게스트의 GET /lists, PATCH /lists/{id}, DELETE /lists/{id}는 모두500. 확정/리포트에도 plan_node/purchase_line 참조가 남아 있다(24,33,38행). | SR05, 최신 커밋 보완 SR06/SR09 | domain_id/slot_key/planning.item 기반으로 라이브 SQL 전환. 구 표를 복원하지 않는다. 실제 축소 DB에서 목록 조회·변경·삭제 및 확정/리포트 저장 계약 검증 추가. P7 사업 규칙 전체 구현과 P0의 SQL 호환 책임을 구분한다. |
| 높음 | `0010_schema_reduction_v1.sql:21–28`의 item/fulfilled_by_item_id 참조에 제약이 없다. 0013까지 적용한 DB에서 planning.item FK는0개. 무작위 revision_id·variant_id를 가진 item INSERT와 미존재 fulfilled_by_item_id UPDATE가 모두 허용됐다. | SR03의 잘못된 신규 입력, SR08의 미존재/범위 참조 거절 | 새 forward 마이그레이션으로 item의 revision/variant/offer/observation 참조와 서로의 관계, requirement와 충족 item의 동일 revision 범위를 강제한다. 미존재 및 타 revision 실제 행 참조 거절, 정상 보유품 저장 테스트를 추가한다. |

라우터 병합 충돌은 현재 해결되어 앱 import가 가능하다. 이전 문서의 충돌 안내는 이번 점검 시점에는 해소된 항목이다. 그러나 import 성공과 테스트 통과만으로 목록 서비스의 축소 DB 호환을 증명하지 못한다. P0 보고서의 “라이브 SQL 전환 완료/완결” 주장은 위 최신 결과에 따라 승인할 수 없다.

## 이번에 직접 확인한 결과

- 검토 전용 DB: localhost:5432 / `p0_acceptance_review_20260913`, PostgreSQL Docker `skn_final-db-1`. 다른 DB를 삭제하지 않았다. 검토 DB는 재현용으로 남아 있다.
- 빈 DB에 db/setup_all.py 성공: 두0010 파일 포함0000–0013 및 도메인·PC51개 시드 적용. 재실행 성공, 미적용 마이그레이션 없음.
- 실제 업무 테이블35개, review_summary.author_ref/review_posted_at 유지 확인.
- DATABASE_URL 및 RAG_TEST_DATABASE_URL을 검토 DB로 지정한 전체 pytest: **207 passed, 2 skipped, 3 subtests passed**, 14.22초. 스킵은 pandas 미설치로 인한 test_rank_review_axis/test_relation_axis이며 DB 스킵이 아니다. 이 결과를 무스킵 완료로 표현하지 않는다.
- 실제 FastAPI TestClient + 실제 PostgreSQL, 의존성 대체 없이: 생성200, 카테고리200, 목록 조회/이름 변경/삭제500.
- 실제 SQL: 잘못된 item/충족 참조 허용. SQL 탐침 변경은 rollback; HTTP 생성 세션은 검토 DB에 남는다.
- 중간에 환경 연결이 끊겨 첫 테스트가 종료143으로 중단됐다. 연결 복구 후 위 전체 테스트와 탐침을 재실행한 결과만 최종 증거로 사용한다.
- 기존 보고서의 PC202→done 및 별도 RAG21/21 CLI 실적은 이번에 개별 재실행하지 않았다. 전체 테스트의 현재 통과와 과거 실적을 구분한다. 위 결함이 확인되어 이 두 경로를 재실행해도 이번 완료 불가 판정은 바뀌지 않는다.

## 재현 산출물

- [독립 탐침](artifacts/p0-completion-probe-2026-09-13.py)
- [실측 JSON](artifacts/p0-completion-results-2026-09-13.json)

저장소 루트에서 실행한다. DATABASE_URL은 반드시 별도의 마이그레이션 적용된 검토 DB로 설정한다(HTTP 요청은 커밋됨).

```bash
PYTHONPATH=. .venv/bin/python docs/agent-tasks/baby/reports/artifacts/p0-completion-probe-2026-09-13.py
# 전체 회귀는 RAG_TEST_DATABASE_URL도 동일 검토 DB로 지정
.venv/bin/python -m pytest -q
```

## 재승인 조건

1. 두 결함을 구현과 DB 제약에서 수정하고 재현 탐침 결과가 목록200/이름 변경200/삭제204 및 잘못된 참조 거절로 바뀔 것. 거절을 검증하도록 탐침/정식 테스트도 갱신한다.
2. 최신 코드로 빈 DB 설치·반복 시드·목록 및 PC/유아 기존 경로 회귀와 SR01–SR09를 다시 검증할 것.
3. P0 보고서에 실제 테스트 범위와 남은 타 과업 경계를 반영할 것. 유아 추천501 자체는 P5 범위이며 이번 P0 결함이 아니다.

이번 검토는 실행 코드를 수정하거나 P0를 complete로 변경하지 않는다.
