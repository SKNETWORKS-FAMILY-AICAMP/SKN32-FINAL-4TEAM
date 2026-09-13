# TrueFit 프론트엔드 작업 지침

## 목표와 일정
- TrueFit 웹 화면을 **실제 백엔드 API와 DB 데이터로 동작**하게 만든다.
  - 화면: 랜딩 → 카테고리 → 조건 대화 → 추천 결과 → 리스트 확정 → 리포트, 로그인·회원가입·회원정보(탈퇴 포함)
  - 카테고리: **컴퓨터와 유아용품 모두**
- 1차 마감: **2026-09-15 해커톤**. 장기 개발: **2026-10-26**까지.
- 10/26로 미룬 것: 신규 가입자 이메일 인증, 비밀번호 재설정 메일.

## 역할 분담
- **프론트(이 작업)**: `frontend/` 폴더만 수정한다.
- **백엔드 팀원**: API, DB 마이그레이션·연결, 카탈로그·유아용품 데이터 적재, 채팅 조건 추출, 추천 엔진 연결.
- 프론트에 필요한 백엔드·DB·인프라·문서 변경은 직접 고치지 않고 **`docs/frontend_외부수정요청.md`**에 기록해 전달한다. 항목마다 대상 파일/영역, 이유(어떤 화면·기능), 제안 내용, 시급도(해커톤 전 / 10월), 담당 영역을 적는다.
- git commit·push·branch 변경은 사용자가 요청할 때만 한다. 작업 브랜치는 `front`.

## 데이터 원칙 — 가짜 데이터 금지
- 계정·장바구니(리스트)·대화·조건·추천 결과·상품·리뷰·리포트는 **모두 API로 받아 DB 기준으로 표시**한다.
  - 로그인은 DB에 저장된 계정만 통과한다. 코드에 박힌 데모 계정·브라우저 계정 저장소를 두지 않는다.
  - 화면용 가짜 로직(고정 상품 목록, 키워드 정규식 조건 파싱, 리뷰 수치 생성 등)을 새로 만들지 않는다.
- API가 아직 없거나 실패하면 **가짜 결과로 대신 채우지 않는다.** 로딩·오류·"서버 준비 중" 상태를 화면에 보여준다.
- 브라우저 저장소(localStorage/sessionStorage)는 **서버 데이터가 아닌 화면 편의 상태**에만 쓴다: 지금 열어 둔 장바구니 ID(`truefit-active-list`), 사이드바 접힘, 언어 설정, 로그인 후 돌아갈 페이지(`truefit-login-return`), 확정 화면 임시 입력(`truefit-confirm-draft`).
- 로그인 토큰은 httpOnly 쿠키로 서버가 관리한다. 프론트는 토큰을 읽거나 저장하지 않는다.
- 채팅 조건 추출에 LLM(Bedrock)을 쓰지 않는다. 자유 입력은 `/session/{id}/message`로 보내고, 서버의 규칙 기반 추출 결과(`fields`, `next_question`, `can_recommend`)를 그대로 그린다. 칩 선택은 `/session/{id}/answer`로 보낸다.
- 검증 쟁점 문장([3-C])과 추천 설명 문장([5])은 서버가 LLM으로 만든다. 프론트는 받은 문장만 표시하고, 생성 중·실패 상태를 구분해 보여준다. 프론트에서 설명 문장을 만들어 채우지 않는다.
- DB는 개발자마다 로컬 Docker(`db/README.md`)를 쓴다. 공용 DB는 이후 AWS 배포 시점에 생긴다.
- 상품 가격·리뷰가 합성 카탈로그인 경우 서버가 주는 표시(출처·예시 여부, `data_notice`)를 그대로 보여준다. 프론트가 임의로 "실제 정보"처럼 꾸미지 않는다.

## API 연결 규칙
- 모든 서버 호출은 **`TF_API` 한 곳**(`js/api.js`의 공통 `fetch` 래퍼)을 거친다: `credentials:'include'`, JSON 본문, 오류 봉투 `{"error":{"code","message","field"}}` 해석, 401이면 로그인 페이지로 보내고 복귀 경로 저장.
  - API 주소는 기본적으로 같은 도메인이다. 로컬에서 API를 다른 포트로 띄웠으면 `?api=http://host:port`로 한 번 열면 같은 브라우저 탭에서 이후 페이지 이동에도 유지된다(sessionStorage).
- 인증은 `TF_AUTH`(`signup`, `login`, `logout`, `me`, `updateProfile`, `changePassword`, `withdraw`, `checkEmail`)로 감싸고, 입력·출력·오류 코드는 **`docs/frontend_외부수정요청.md` §A-4와 동일**하게 맞춘다.
- 세션·채팅·추천·리스트·리뷰 API는 같은 문서 §D-4의 계약을 기준으로 한다. 화면에 필요한데 계약에 없는 필드·API는 **코드에서 추측해 만들지 말고 문서에 먼저 추가**해 백엔드와 합의한다.
- 용어 변환(카테고리 `pc`↔`computer`, 슬롯명 프로세서↔CPU 등)은 `TF_PLAN`/`tfUiCategory`/`tfApiCategory`(`js/core.js`) 한 곳에서만 한다.
- 권한 규칙(기술기획서 §3): 비로그인도 대화·추천·결과 확인 가능(서버의 `truefit_guest` 쿠키). 리스트 확정·리포트·가격 알림·리뷰 작성·회원정보는 로그인 필요. 확정 시 비로그인이면 `login.html`로 보내고 로그인 후 `confirm.html`로 복귀한다.
- 회원 탈퇴는 현재 비밀번호 확인 후 요청한다(회원정보 화면의 확인창에 비밀번호 입력란 포함).

## 디자인 원본 반영 규칙
- 디자인 원본은 사용자가 전달하는 `C:\Users\green\Downloads\TrueFit.html`이며 UI 수정이 계속 들어온다. 랜딩 화면 마크업·CSS의 출처다.
- 디자인 원본 HTML은 크기가 크므로 `frontend/` 내부에 복사하거나 보관하지 않는다.
- 새 원본은 `C:\Users\green\Downloads\TrueFit.html`에서 직접 확인하고 현재 `frontend/index.html` + `css/` 구현과 비교한다. 필요한 레이아웃·CSS·문구 변경만 해당 파일에 이식한다. 원본은 여전히 랜딩(단일 파일 SPA 시절 디자인)만 담고 있으므로, 조건 대화·추천 결과 등 내부 화면 디자인 변경은 원본의 해당 섹션 마크업을 기준으로 대응하는 페이지 파일(아래 화면 지도)에 옮긴다.
- 레이아웃·CSS·문구는 원본을 우선한다. 개발 목적으로 원본과 달라진 곳에는 `TF-DEV:` 주석을 단다.
- 이미지는 `frontend/assets/` 파일로 참조한다. 원본의 base64 내장 이미지는 파일로 추출해 교체한다.
  - `truefit-logo.png` = 워드마크 (원본 `project_asset/truefit-transparent.png`)
  - `truefit-icon.png` = 아이콘 (원본 `project_asset/logo.png`)
  - CSS 파일(`css/*.css`) 안에서 `url(...)`로 이미지를 참조할 때는 **CSS 파일 위치 기준** 상대경로다(`css/planner.css`에서는 `../assets/...`). HTML에서 쓰는 `./assets/...`와 다르니 혼동하지 않는다.

## 화면 지도 (멀티페이지 — 2026-09-11 전환)
UX와 UI 담당이 화면 단위로 나눠 작업할 수 있도록, 해시 라우트 SPA에서 **페이지당 별도 `.html` 파일**로 바꿨다. 화면 이동은 실제 페이지 이동(`location.href`)이며, 서버 데이터는 페이지를 열 때마다 새로 받는다(브라우저에는 "지금 열어 둔 장바구니 ID"만 남는다 — 위 데이터 원칙 참고).

| 화면 | 파일 | 렌더 함수 | 이 화면만 쓰는 스크립트 |
|---|---|---|---|
| 랜딩 | `index.html` | (정적 마크업 + `landing.js`) | `js/pages/landing.js` |
| 카테고리 선택 | `category.html` | `categoryPage()` | `js/pages/category.js` |
| 조건 대화 | `conditions.html` | `conditionsPage()` | `js/pages/conditions.js` |
| 추천 결과 | `results.html` | `resultsPage()` | `js/pages/results.js` |
| 추천 과정(로그) | `logs.html` | `logsPage()` | `js/pages/logs.js` |
| 리스트 확정 | `confirm.html` | `confirmPage()` | `js/pages/confirm.js` |
| 리포트 | `report.html` | `reportPage()` | `js/pages/report.js` |
| 로그인 | `login.html` | `loginPage()` | `js/pages/auth.js` (login/signup/account 공용) |
| 회원가입 | `signup.html` | `signupPage()` | 〃 |
| 회원정보 | `account.html` | `accountPage()` | 〃 |

**공용 스크립트** (여러 페이지가 로드):
- `js/api.js` — `TF_API`, `TF_AUTH`, 오류 메시지. **모든 페이지**.
- `js/core.js` — `$`/`esc`/`won`, `tfPlan` 상태, `TF_PLAN`(API 래퍼), `go()`/`tfHref()`(페이지 이동), `tfSetCategory`/`choose`(카테고리 선택 — 랜딩 퀵스타트·푸터 바로가기에서도 씀), `tfSendToLogin`/`tfLogout`. **모든 페이지**.
- `js/footer.js` — 모든 페이지에 중복 삽입된 `<footer>`의 안내창·서비스 바로가기 동작. **모든 페이지**.
- `js/planner-shell.js` — 사이드바·단계 표시줄·`shell()`·장바구니 이름변경삭제, 추천 결과 공용 조각(리뷰 지표, 후보 비교 오버레이, 폴링). **category/conditions/results/logs/confirm/report 6개**.
- `js/pages/auth.js` — `authShell()`, `loginPage`/`signupPage`/`accountPage`. **login/signup/account 3개**. 로그인·회원가입 페이지는 스크립트 로드 뒤 `window.addEventListener('DOMContentLoaded', ()=>loginPage())` 형태의 **인라인 부트스트랩 한 줄**로 그 페이지의 렌더 함수를 호출한다(각 HTML 파일 맨 아래 `<script>`).
- `js/i18n.js` — 영문 전환. **모든 페이지**, 항상 스크립트 목록 맨 마지막.

**새 페이지를 추가할 때**: 화면에 필요한 스크립트만 붙인 `.html` 파일을 만들고, `js/pages/`에 렌더 함수 + 그 페이지 전용 이벤트 리스너를 작성한 뒤 파일 맨 끝에서 스스로 호출한다(`categoryPage();`처럼). 로그인 필요 화면은 `report.js`를 참고: `TF_AUTH.ready.then(()=>{...})`로 서버 로그인 확인을 기다린 뒤 그리거나 `tfSendToLogin('페이지파일.html')`로 보낸다.

**주의 — 인라인 `<script>`에는 `defer`가 안 먹는다.** HTML 스펙상 `src` 없는 인라인 스크립트의 `defer`는 무시되고 즉시(파싱 중) 실행되므로, `js/core.js` 등 외부 지연 스크립트가 아직 실행되기 전에 돌아 `ReferenceError`가 난다. login/signup/account의 부트스트랩처럼 외부 스크립트가 정의한 함수를 인라인에서 불러야 하면 반드시 `window.addEventListener('DOMContentLoaded', () => ...)`로 감싼다.

## 코드 규칙
- 템플릿 문자열 렌더와 `$`/`esc`/`won`/`go`/`toast` 유틸은 현재 유지한다. 새 코드와 수정하는 함수는 읽기 쉬운 여러 줄 형식으로 작성하며 한 줄 압축을 새로 만들지 않는다.
- 서버에서 받은 값·사용자 입력을 HTML에 넣을 때는 반드시 `esc()`를 거친다.
- 비동기 호출 중에는 버튼 중복 클릭을 막고(`tfBusy()`), 응답이 늦게 와도 다른 화면을 덮어쓰지 않게 한다(`tfPlan.seq`/`listId` 비교 패턴을 따른다).
- 새 전역 이름은 `TF_`/`tf` 접두어, 새 브라우저 저장 키는 `truefit-` 접두어를 쓴다.
- 한국어 문구를 추가하면 영문 전환 사전(`DICT`, `js/i18n.js`)에도 번역을 추가한다.

## 실행과 검증
- 백엔드: `uv run uvicorn src.api:app --reload --host 127.0.0.1 --port 8000` (DB는 `db/README.md` 절차, Docker 필요)
- 프론트: 백엔드와 같은 도메인에서 서빙하는 설정이 들어오기 전까지는 `uv run python -m http.server 5500 --bind 127.0.0.1 --directory frontend` → `http://127.0.0.1:5500/index.html` (8080은 Windows에서 OS 예약으로 바인딩이 거부될 수 있어 5500 사용) (이 경우 API CORS 설정이 필요 — 외부 수정 요청 문서 참고)
- 수정 후 in-app 브라우저로 직접 확인하고, 콘솔 에러와 실패한 네트워크 요청을 확인한다. 확인 흐름:
  1. 랜딩 로고·배경 전환·헤더 버튼
  2. 회원가입 → 로그아웃 → 같은 계정 재로그인 → 회원정보 수정 → 비밀번호 변경 후 새 비밀번호로 로그인 → 탈퇴 후 로그인 불가
  3. PC: 카테고리 → 조건 대화 → 추천 결과(후보 교체·리뷰 상세) → 확정(비로그인 → 로그인 → 복귀) → 리포트
  4. 유아용품: 같은 흐름
  5. 장바구니 목록·새로 만들기·이름 변경·삭제, 사이드바 접기, 로그인 상태에서 새로고침해도 이어지는지
  6. API 오류·미구현(501)일 때의 화면 표시, 영문 전환, 모바일 폭(375px, 가로 스크롤 없는지)
- 백엔드 API가 준비되지 않아 확인할 수 없는 흐름은 완료로 보고하지 않고 **"미확인(백엔드 대기: 어떤 API)"**으로 명시한다.

## 보고
- 작업이 끝나면: 변경 파일과 요약, 확인한 흐름 / 미확인 흐름과 대기 중인 API, `docs/frontend_외부수정요청.md` 갱신 내용을 보고한다.
