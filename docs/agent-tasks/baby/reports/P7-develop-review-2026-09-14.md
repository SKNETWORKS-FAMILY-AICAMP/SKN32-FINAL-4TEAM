# P7 develop 전환 결과 검토 — 2026-09-14

## 판정

**P7 partial 유지. P9 운영 검증 단계로 완료 인계할 수 없다.** P8의 후기 독립 구현은 기존 P0/P6 조건 아래 가능하나 확정 이벤트 통합 완료는 P5/P7 보완 후 판단한다.

대상: HEAD `110f6ca` + 현재 P7 미커밋 변경, [P7 보고서](P7.md), [P7 지시서](../P7_lists_reports.md). 테스트는 재실행하지 않았다. 보고서의 문법 검사 통과는 인정하지만 DB 테스트6건은 전부 skipped이며 D7 실측은 없다. 아래는 소스·화면 adapter·테스트의 정적 대조 결과다.

## 인정하는 변경

purchase_line에 candidate.qty를 pack_count로 저장하고 단가×수량을 line_amount로 쓰는 변경, 시점별 합계, offer/observation/variant 관계 검사, revision/run 잠금과 If-Match 검사, 확정 snapshot 및 이벤트 쓰기 구조는 확인했다. 과거 단가만 합산/수량1 고정 문제를 수정하는 방향은 맞다. 실제 DB 실행·rollback·재확정 멱등 성공은 아직 입증되지 않았다.

## 승인 차단 사항

### R1 — 필수 수량·시점 충족 검증 없이 확정

list_service.confirm은 selected 후보만 읽고 그 행들의 가격·검증 상태를 검사한다. 전체 active requirements와 보유량을 모아 P4 재계산하지 않는다. req.required/quantity를 SELECT하지만 충족 판단에 쓰지 않으며 missing_requirements는 무조건 []로 저장한다.

선택하지 않은 필수품, 필요한 수량보다 적게 담은 필수품, now 필수품을 later로 옮긴 경우가 확정에서 누락될 수 있다. 선택된 후보의 safety pass만으로 장바구니 전체가 유효하지는 않다.

수정: 전체 필요량·검증된 보유량·현재 선택 상태를 권위 있는 저장소에서 읽어 P4 재계산하고 필수량/단위/시점/예산이 충족된 경우에만 확정한다. 부족한 필수품·일부 수량·이연·보유 충족을 포함한 거절/성공 및 부분 행 없음 사례를 확인한다.

### R2 — 최신 조건과 추천 결과의 일치 확인 없음

confirm은 가장 최근 completed run만 선택한다. 이후 running/failed/stale run이 있거나 조건이 변경됐어도 과거 completed 결과를 쓸 수 있다. 현재 If-Match는 요청과 revision의 버전 일치만 확인하며 선택한 run이 현재 조건에 기반하는지는 확인하지 않는다.

수정: P5와 current run 및 조건 변경/후보 편집의 유효성 계약을 맞추고 과거 조건의 결과는 거절한다. 단순 run.draft_lock_version==현재 lock_version 비교는 정상 후보 편집에도 버전이 증가하므로 충분한 설계가 아니다. 조건 snapshot/hash 또는 명시적인 결과 유효성 기준을 사용한다. 조건 변경 후 재추천 전, 새 실행 진행/실패 중 과거 run 확정 거부를 검증한다.

### R3 — 화면에서 If-Match를 보내지 않음

frontend/js/core.js의 TF_PLAN.confirm은 body만 보낸다. 반면 새 confirm 서비스는 draft 요청의 If-Match를 필수로 요구하므로 현재 확인 화면의 정상 확정 요청도422가 된다. PC도 같은 adapter를 사용한다.

src/routers/lists.py는 헤더를 int(if_match)로 직접 변환한다. 잘못된 문자열은 FastAPI 입력 검증이 아니라 처리되지 않은 ValueError가 될 수 있다.

수정: 최신 결과 lock_version을 확정 헤더에 포함하고409시 새 상태를 안내한다. 헤더 타입을 선언하거나 변환 오류를 명시적으로422 처리한다. 브라우저 확정 성공, 누락/잘못된 값422, stale409, PC 회귀를 확인한다.

### R4 — 보유 snapshot과 팩 단위 정보가 불완전함

baby_confirmation.owned는 선택된 구매 후보의 match_spec에서만 추출한다. 구매 없이 보유만으로 충족된 슬롯은 빠진다. 같은 requirement에 여러 후보가 선택되면 owned가 중복될 수도 있다. purchase snapshot.unit_qty는1로 고정되어 실제 포장 수량 정보를 보존하지 않는다. _report는 owned를 반환하지 않아 저장하더라도 보고서에 드러나지 않는다.

수정: 전체 필요량에서 보유 정보를 추출·중복 제거하고 실측 포장/단위 값을 기록한다. 보고서 응답에도 계약된 보유 정보가 표현되도록 연결한다. 보유만 충족하는 슬롯+구매 슬롯, 일부 보유+구매, 팩 상품을 확인한다. 모든 필요품이 보유로 충족된 경우의 구매0 확정 정책도 명시한다.

### R5 — 저장된 pass만 확인하고 현재 근거 유효성은 재검사하지 않음

baby verdict SQL은 validation_result.status만 집계한다. 설명서 철회·상품 적용 승인 해제·현재 필수 규칙 누락을 확인하지 않는다. 후보에 과거 pass 한 건만 있어도 fail/unknown 행이 없으면 pass로 간주한다.

수정: P3의 현재 근거/적용/필수 규칙 검증 경계를 확정 시 호출한다. 과거 pass 후 자료 철회, 규칙 누락 및 다른 requirement 근거가 확정을 통과하지 못하게 한다. P3 미완료를 이유로 안전 검증 없이 확정 완료를 선언하지 않는다.

## 추가 미충족 사항

- 현재 lists 라우터와 list_service에는 develop의 /alert 연결이 여전히 없다. D7의 기존 price_watch 경로 유지 검증은 미충족이다. P0의 동일 지적과 중복 작업하지 말고 하나의 복원 작업으로 해결한다.
- _report는 owner_display_name을 현재 app_user에서 조회한다. 보고서의 “snapshot만 조회”는 엄밀히 사실이 아니다. 작성자명 변경이 과거 리포트에 반영되는 정책인지 확정하고 설명을 맞춘다. 상품/가격 snapshot 보존과 구분한다.
- 재현 절차의 migrate.py up만으로는 카탈로그를 사용하는 테스트 전제가 충족되지 않는다. 전용 빈 DB에 setup_all 및 필요한 시드를 적용하는 완전한 절차를 기록한다.
- 기존 테스트 수정은 if_match 인자 추가2곳뿐이다. 전부 skipped인 결과를 D7의 새 검증으로 세지 않는다. 위 신규 경계별 실제 DB/HTTP 테스트가 필요하다.

## 다음 단계

| 단계 | 진행 판단 |
|---|---|
| P8 | 후기 독립 작업 가능. 실제 확정 이벤트 생성·중복 방지 통합 검증은 P7 실제 DB 검증 후 |
| P9 | 점검 스크립트/적용 절차 준비 가능. 전체 사용자 흐름 및 운영 준비 완료 인계는 불가 |

P5 결과 adapter·동시 편집 및 P6 인증 경합 등 선행 검토 항목도 별도로 남아 있다. 우선 P7의 R1/R2로 확정 유효성을 보장하고 R3 화면 연결, R4/R5 snapshot·근거 검증을 보완한다. 이후 새로운 D7 영향 경로만 실측하며 과거 전체 테스트를 반복할 필요는 없다.
