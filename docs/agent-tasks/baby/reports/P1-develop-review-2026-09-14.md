# P1 develop 전환 결과 검토 — 2026-09-14

## 결론

**P1 partial 유지. P2 및 P6의 독립 구현은 착수 가능하지만 P1 완료를 전제로 한 통합 승인은 보류한다.** P0 미완료 외에도 P1의 활성 규칙 선택과 보유량 입력 계약에 남은 작업이 있다. 전체 재작성은 필요하지 않다.

검토 기준: [P1 최신 v3 보고서](P1.md), [P1 지시서](../P1_sessions_conditions.md)의 ACTIVE DB CONTRACT, HEAD `d7e6349`와 현재 미커밋 변경. 현재 작업 트리에는 P2의 DTO/stage2/stage4/PlanRepo 수정도 함께 있으므로 이를 P1 검증 실적으로 귀속하지 않는다. 보고서 테스트는 재실행하지 않았고 소스·테스트 내용만 대조했다. 서비스 DB에는 접근하거나 적용하지 않았다.

## 인정하는 실적

보고서의 신규 D1 테스트6건 및 기존 세션 HTTP11건 통과 기록을 재사용한다. 실제 domain_version 연결, 같은 게스트 두 목록 접근, 다른 게스트 GET/PATCH 거부, exact=false 재조회, 조건 수정·재조회, PC 업로드 저장·413·확장자422를 확인하는 테스트가 존재한다.

실제 수정도 확인했다: FileTooLarge 복원, SpecFileIn 및 /spec-file 라우트 복원, 정식 load_owned_draft 사용, computer/upgrade에서 accepts_spec_file=true. 이 부분은 유효한 P1 성과다. frontend/js/core.js의 tfSetCategory도 다른 카테고리 선택 시 새 목록을 만드는 기존 흐름을 유지한다. 신규 테스트의 동일 목록 카테고리 재결합만으로 브라우저 전환 전체를 검증했다고 확대 해석하지 않는다.

## P1 자체 보완 사항

### R1 — 활성 도메인 선택 계약을 충족하지 않음

`src/repo/plan_repo.py:22`의 published_domain_version은 status와 무관하게 최신 version을 선택한다. WHERE는 d.code만 확인하므로 draft뿐 아니라 disabled도 선택할 수 있다. `:38`의 bind_domain_version은 이 결과를 그대로 사용하며 동일 카테고리 재요청도 최신 버전으로 재결합한다.

P1 지시서는 활성 domain의 실제 버전 선택과 revision의 버전 유지를 요구한다. 신규 `test_d1_category_switch_pins_distinct_domain_version_rows`는 baby.status='draft'를 오히려 성공 조건으로 고정한다. 따라서 특정 카테고리 UUID 연결의 증거는 되지만 활성 게시 규칙 선택의 증거는 아니다. develop 시드가 draft라는 사실은 지시서의 활성 조건을 자동 폐기하지 않는다.

보완: 유효한 baby 정의/해시와 활성화 준비를 P0/P2와 맞추고 활성 버전 선택을 적용한다. disabled/draft의 실행 규칙 사용을 거부하는 경계를 명시한다. 동일 카테고리 재요청 시 이미 고정한 버전을 유지하고 규칙 업데이트는 명시적인 새 revision 절차로 구분한다. 활성/비활성 선택과 신규 버전 추가 후 기존 revision 고정 사례를 검증한다. 초안 조건 수집을 계속 허용할 경우에도 그것을 활성 추천 규칙 바인딩 완료로 보고하지 않는다.

### R2 — P2에 전달할 명시적 보유 수량·단위 정규화 누락

`src/services/session_service.py:61`의 normalize_baby_conditions는 owned_items를 list로 복사할 뿐이다. `:351` 이후 list 검증은 집합 membership와 dict.fromkeys에 의존한다. `{label, qty, unit_code}` 형태의 항목을 그대로 전달하면 해시 불가능한 dict에 대한 TypeError가 발생할 수 있다. 현재 문자열 입력은 보존하지만 명시적 수량·단위 입력과 P2 인계 payload는 구현/증명되지 않았다.

보완: 문자열 UI 호환을 유지하면서 보유 항목을 typed 형태로 정규화하고, 양수·유한 수량/허용 단위/없음 배타성/중복 처리 규칙을 정한다. P2가 요구하는 조건 출처와 실제 payload 예시를 보고서에 기록한다. 총2개 필요/1개 보유 및 여러 개 보유 입력이 HTTP→정규화→P2에서 정확하게 전달되는 경계 테스트가 필요하다. 목록의 dict/잘못된 요소는 500 대신 명시적 검증 오류로 처리한다.

### R3 — 업로드 허용 플래그와 서버 동작의 불일치 (보완 권고)

`src/services/session_service.py:519`의 attach_spec_file은 소유권·확장자·용량만 검사하며 category/mode는 확인하지 않는다. baby 또는 computer/build도 직접 POST하면 spec_file_name/current_specs를 저장할 수 있다. 신규 테스트는 “baby의 업로드도 거절해야 한다”는 주석을 달았지만 실제 POST 거절 검사는 없고 false 플래그만 확인한다.

D1의 명시적 false 표시 조건은 충족했으므로 이를 업로드 복구 전체 실패로 보지는 않는다. 다만 “computer/upgrade에서만 허용”을 서버 정책으로 일치시키고 baby/build POST 거부 및 조건 미변경을 검사해야 한다. 보고서에서 실제 검증한 플래그와 검증하지 않은 요청 거부를 구분한다.

## 보고서 정확성 보완

- 전체219 passed/12 failed/30 skipped를 전체 통과로 인정하지 않는다. “30건은 pandas” 서술은 P0 보고서의27건 rag +1건 P3 import +2건 pandas 설명과 상충한다. 실제 실행 로그에 맞춰 정정한다. 새로운 실패가 없다는 주장과 현재 작업 트리의 추가 P2 변경 검증은 별개다.
- 기존 SS01~SS06의 d96ccd2 재검증 절은 완전 축소 DB 기록이다. develop DB에서11건을 다시 통과했다는 최신 new_tests 기록과 구분하여 같은 근거라고 연결하지 않는다.
- curl 재현 예시의 JSON 요청은 `Content-Type: application/json`과 두 번째 세션 생성/쿠키 절차를 포함하도록 보완한다.
- D1:pass는 테스트6건의 통과를 의미할 수 있지만 R1/R2를 포함한 P1 전체 계약 완료를 의미하지 않는다.

## 다음 단계 인계 판단

| 단계 | 진행 가능 범위 | 완료 승인 조건 |
|---|---|---|
| P2 | 카탈로그·plan_node 기반 필요량 저장 전환 착수 가능 | P1 R2의 입력 payload와 R1의 규칙 버전 계약을 함께 확정하고 P0 무결성 보완 후 통합 검증 |
| P6 | 게스트 소유권·계정 설정·인계의 독립 작업 가능 | 기존 인증 실적 재사용; P0 공통 게이트 및 실제 P1 인계 경계 확인 |
| P3/P4 | provider 경계·순수 계산 구현 준비 가능 | 각각 P0/P2 및 P3 산출물 의존 유지 |
| P5 이후 | 독립 코드 준비는 가능, 정상 추천·확정 통합 완료는 보류 | P0 R1~R4, P1 R1/R2 및 원래 선행 단계 완료 |

[P0 검토](P0-develop-review-2026-09-14.md)의 교차 참조·JSON 검증·알림·확정 수량 문제는 여전히 별도의 선행 차단 사항이다. 서비스 DB 미적용 자체를 P1 결함으로 보지 않는다. 다음 검증은 위 변경 경계만 수행하며 기존 전체 테스트를 반복할 필요는 없다.
