# 유아용품 에이전트 구현 작업 목록

**현재 목표: develop `da79839` DB 설계에 맞춘 유아 서비스 전환(v3). 문서만 갱신했으며 실제 코드/DB 전환은 미완료다.** P0~P9는 기존 구현을 재사용하면서 영향을 받는 저장·조회·검색 경로를 수정한다. 처음부터 전부 다시 만들지 않는다. `개발 역할 분담`은 적용하지 않는다.

## ENTRYPOINT

1. [전환 계약](DEVELOP_DB_TRANSITION.md)과 [목표 스키마](schema-v1.md)를 읽는다.
2. [공통 계약](CONTRACTS.md)과 아래 개별 작업의 **ACTIVE DB CONTRACT**를 읽는다. 과거 지시의 상충 DB 매핑은 폐기됐다.
3. 선행 작업의 실제 코드와 v3 수용 결과를 확인한다. 과거 P0~P6 보고서만으로 develop 호환 완료를 판단하지 않는다.
4. 각 문서의 EDIT → IMPLEMENT → Dn ACCEPTANCE → HANDOFF를 수행한다. 결과는 기존 reports/Pn.md에 새 v3 절로 추가한다.
5. 기계 판독은 [manifest.json](manifest.json)을 사용한다. contract_version=3은 내부 계약이며 API URL 버전 변경이 아니다.

## CURRENT STATUS

- P0: develop 설치 체인·저장소 전환이 선행 작업. 이전 item FK 해결 경험/검증 의도는 재사용한다.
- P1/P2/P6: 조건·규칙·인증 로직을 재사용하고 유지 테이블로 연결한다.
- P3: PostgreSQL RAG 의존 제거와 외부 provider 구현 필요. backend 미설정 경로 구현과 실제 외부 연결 검증은 별도 게이트다.
- P4: 계산 로직을 재사용하고 보유량/식별자 DTO를 수정한다.
- P5/P7: candidate 편집과 purchase_line 확정을 연결한다.
- P8: 유지된 review_revision/source 구조로 유아 후기 저장·집계를 연결한다.
- P9: 전용 develop DB에서 변경 경로를 검증하고 서비스 연결 전환 절차를 만든다.

기존 테스트 실적은 변경 없는 경로에만 재사용한다. [병합 검증](reports/merge-validation-2026-09-13.md)의 실패는 기록으로 보존한다. 최신 문서 갱신에서 기존 테스트를 다시 실행하지 않았다.

## TASKS

| ID | 작업 문서 | 구현 선행 조건 | 완료 시 제공물 |
|---|---|---|---|
| P0 | [develop DB·공통 계약·저장소 전환](P0_schema_contracts.md) | 없음 | develop 설치 체인·공통 adapter·DB 무결성 |
| P1 | [DB 접속·게스트 세션·조건 수집](P1_sessions_conditions.md) | P0 | DB 연결·쿠키·조건 저장/조회 API |
| P2 | [유아 카탈로그·단위·필요 품목 규칙](P2_catalog_requirements.md) | P0 | 멱등 상품 적재·필요 품목 규칙·후보 DTO |
| P3 | [후보 안전 조건·설명서 검증·근거 연결](P3_verification_rag.md) | P0, P2 | 후보별 판정·근거 JSON·권한 재검사 |
| P4 | [필수품·예산·구매 시점 최적화](P4_basket_optimizer.md) | P0, P2, P3 | 필수품·예산·구매 시점 최적화 결과 |
| P5 | [추천 실행·저장·결과·후보 편집 API](P5_recommendation_http.md) | P1, P2, P3, P4 | 추천/조회/편집 API·실제 브라우저 흐름 |
| P6 | [가입·비밀번호 인증·설정·게스트 인계](P6_authentication.md) | P1 | 가입/로그인/계정·게스트 인계 |
| P7 | [목록·확정 스냅샷·리포트·판매처 이동](P7_lists_reports.md) | P5, P6 | 목록/확정/리포트·스냅샷 보존 |
| P8 | [유아 후기·파일 기반 정제·요약/통계·행동 기록](P8_reviews_feedback.md) | P0, P6; 최종 이벤트 통합 검증은 P5·P7 | 후기/파일 정제/요약·통계/피드백 검증 |
| P9 | [운영 검증·자료 처리 확장·RAG 전환 게이트](P9_operational_validation.md) | P0, P3, P5, P7 | develop 설치·외부 검색·서비스 전환 검증 |

## EXECUTION ORDER

P0 → P1/P2/P6의 전환 → P3/P4 → P5 → P7 → P9. P6는 P1 소유권 출력에 의존한다. P8은 P0/P6 후 시작하고 P5/P7 이벤트 통합을 마지막에 검증한다. 실제 의존 관계는 manifest의 depends_on/integration_depends_on이 우선한다. 외부 backend가 없어도 P3-D3-01과 독립 계산 작업은 가능하지만 D3-02 및 검증 포함 추천 완료는 미승인이다.

## DISPATCH PROMPT

```text
<개별 작업 문서 경로>의 ACTIVE DB CONTRACT를 구현하라.
DEVELOP_DB_TRANSITION.md, schema-v1.md, CONTRACTS.md와 선행 작업의 실제 v3 산출물을 확인하라.
develop da79839 DB 설계를 유지하고 과거 완전 축소 SQL이나 PostgreSQL rag를 복원하지 마라.
기존 작업을 보존하고 영향을 받는 코드·시드·fixture·의미 있는 검증을 함께 수정하라.
보고서의 변경 없는 테스트 실적은 재사용하되 새 DB/검색 경로의 증거로 오인하지 마라.
reports/Pn.md에 v3 절을 추가하고 각 Dn 사례, 재현 방법, 실제 결과와 미충족 조건을 기록하라.
개발 역할 분담은 적용하지 않는다.
```

[서비스 흐름·구현 현황](../../유아용품_서비스흐름_구현현황_2026-09-12.md)의 최상단 표가 비개발자용 현재 요약이다.
