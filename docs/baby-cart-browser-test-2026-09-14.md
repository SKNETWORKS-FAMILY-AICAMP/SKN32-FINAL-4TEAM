# 유아용품 장바구니 실제 브라우저 테스트 — 2026-09-14

판정: **종단 간 통과 실패**. 신규 장바구니 생성과 조건 입력, 추천 응답까지 진행되지만 선택 상품이 0개라 리스트 확정·리포트로 진행하지 못한다.

## 실행 환경

- 원본 FastAPI 앱을 `http://127.0.0.1:8002`에서 실행, Chromium headless 실제 DOM 클릭·입력 사용. API 응답 모킹 없음.
- 별도 PostgreSQL 16.15, pgvector 0.6.0, 저장소의 0000~0014 마이그레이션 및 기본 카테고리 seed 적용.
- 기본 `catalog_demo_v1.json`의 합성 상품 188개 적재. `MOCK_MODE=1`, 외부 검색 provider 및 설명서 코퍼스 별도 준비 없음.
- 비로그인 신규 브라우저로 테스트. 데스크톱 1440×1000, 모바일 viewport 390×844.
- 기존 DB·상품·계정과 앱 소스는 변경하지 않음. 테스트 계정 생성·실제 주문·결제 없음.
- 초기에 PGlite에서 발생한 prepared statement 충돌·연결 실패는 테스트 환경 문제로 분리했다. 아래 판정은 실제 PostgreSQL과 원본 앱에서 재실행한 결과에 근거한다.

## 재현 흐름과 결과

1. 홈 → ‘나의 장바구니 만들기’ → ‘유아용품’: 통과.
2. ‘0~3개월’, ‘기저귀·배변’, ‘특이사항 없음’, 보유 물품 ‘없음’, ‘예산은 100만원입니다’ 입력: 요청 모두 HTTP 200. 추천 버튼 표시.
3. ‘이 조건으로 추천 보기’: HTTP 202, 결과 조회 HTTP 200. 결과 화면 도달.
4. 결과는 상품 0개·합계 0원, 확정 버튼 disabled: **진행 차단**.
5. 새 브라우저 컨텍스트에 쿠키와 localStorage를 유지해 결과 다시 열기: 동일 장바구니·조건·결과 유지.
6. 결과 채팅에 ‘기저귀 담아줘’: PC 부품을 예시로 든 이해 실패 답변. 상품 추가 없음.
7. 조건 화면 재진입: 입력 내용 유지, ‘없음’ 표시 결함 지속.
8. 사이드바에서 해당 테스트 장바구니 삭제 → 카테고리로 이동 → 새로고침: 남은 장바구니 0개, 정상.

실제 PostgreSQL 실행에서 관찰한 기본 흐름 API 오류 및 JavaScript 실행 예외는 없었다. 비로그인 `/auth/me`의 401은 예상된 응답이다. HTTP 성공만으로 기능 통과 판정하지 않았다.

## 발견 사항

### 1. 기저귀·물티슈 후보를 선택하지 못해 확정 진행 불가

예산 1,000,000원에서도 선택 상품이 0개다. 테스트 DB `engine.validation_result`에서 기저귀·물티슈 후보의 `status=unknown`, `message=no_reviewed_rule_for_category`를 확인했다.

`src/rag/verification.py:14`의 검증 규칙 목록에는 stroller만 있고 검토 완료된 비적용 목록은 비어 있다. `src/engine/stage3c_verify.py:287`은 나머지 품목을 unknown으로 분류하고 298행에서 pass만 선택 가능하게 한다. 안전 확인을 생략해야 한다는 뜻이 아니라, 기본 유아용품 준비 흐름을 완료할 수 있는 검증 규칙·데이터가 부족하다는 의미다.

수량 증감, 개별 상품 제거, 대체 후보 선택, 확정 저장, 로그인 후 이어가기, 리포트는 이 재현 흐름에서 선행 상품 선택이 막혀 **미검증**이다. 해당 기능 자체가 실패했다고 단정하지 않는다.

### 2. 검증 규칙 부재를 예산 부족으로 안내

화면에 ‘예산 안에서 채울 수 없는 필수 품목이 있어요.’가 두 번 표시된다. 실제 관찰된 이유는 위 검증 규칙 부재다. `src/services/recommendation_service.py`의 headline은 decision.feasible이 false인 모든 경우를 예산 문제로 표현한다. 사용자가 예산을 늘려야 하는 문제로 오해할 수 있다.

### 3. ‘없음’ 응답이 미응답처럼 표시

‘특이사항 없음’, 보유 물품 ‘없음’을 정상 제출하고 추천 가능 상태가 됐는데도 조건 요약에는 두 필드 모두 ‘아직 확인되지 않았어요’가 표시된다. 새로 열어도 같다.

`src/services/session_service.py:431`은 유아용품의 없음 응답을 빈 배열로 저장한다. 같은 파일 182행의 `_display`는 빈 배열을 None으로 표시하고, 조건 화면은 이를 미응답 문구로 렌더링한다. 응답 자체가 유실된 것은 아니다.

### 4. 유아용품 결과 화면에 PC용 표현과 안내

‘0개 부품으로 구성했어요’, ‘마음에 안 드는 부품’이 출력된다. ‘기저귀 담아줘’에는 ‘부품 이름(예: 그래픽카드)’을 알려달라는 답변이 온다. 이 환경에서 직접 담기 요청으로 빈 장바구니를 해결할 수 없었다. 결과 요약의 PC 표현은 `frontend/js/pages/results.js`의 `tfResultSummaryHtml`에서 확인할 수 있다.

### 5. 모바일 가로 넘침

결과 화면에서 viewport를 390×844로 변경한 뒤 `window.innerWidth=390`, `document.documentElement.scrollWidth=780`을 관찰했다. 전체 페이지 스크린샷에도 오른쪽으로 큰 빈 패널이 나타난다. 모바일 기기 실물 테스트는 아니며 Chromium viewport 검증이다.

## 증거

- [추천 결과 화면](baby-cart-browser-artifacts-2026-09-14/results.png)
- [조건 입력 완료 화면](baby-cart-browser-artifacts-2026-09-14/conditions.png)
- [직접 담기 응답](baby-cart-browser-artifacts-2026-09-14/direct-add.png)
- [재진입 후 조건 요약](baby-cart-browser-artifacts-2026-09-14/persisted-conditions.png)
- [모바일 전체 화면](baby-cart-browser-artifacts-2026-09-14/mobile.png)
- [삭제 후 화면](baby-cart-browser-artifacts-2026-09-14/deleted.png)
- [기본 흐름 HTTP 상태 기록](baby-cart-browser-artifacts-2026-09-14/network.json)

이 결과는 로컬의 기본 합성 카탈로그 시나리오에 대한 판정이다. 실제 배포 사이트, 실상품 카탈로그, 외부 검색·LLM 연결 환경 전체를 검증한 것은 아니다.
