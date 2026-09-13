# 프론트 작업에 따른 외부 수정 요청

- 작성: 2026-09-11 (4차 갱신) · 프론트 작업(`front` 브랜치)
- 목적: 프론트는 `frontend/` 폴더만 수정한다. 그 밖(백엔드·DB·데이터·인프라·문서)에서 필요한 변경을 이 문서에 모아 담당자에게 전달한다.

## 결정 사항

| 항목 | 결정 |
|---|---|
| 역할 분담 | 프론트는 화면과 API 호출만. **API·DB·데이터 적재·조건 추출·추천 엔진 연결은 백엔드 팀원**이 이 문서 기준으로 구현 |
| 데이터 | 화면은 **실제 API와 DB 데이터로만** 동작한다. 브라우저 가짜 데이터·데모 계정을 쓰지 않는다. API가 없으면 화면은 오류/준비 중 상태를 보여준다 |
| 인증 | 이메일 + 비밀번호. 로그인 토큰은 httpOnly 쿠키. **이메일 인증은 2026-10-26로 연기** |
| 카테고리 | **컴퓨터와 유아용품 모두** 해커톤(9/15)까지 |
| 채팅 조건 추출 | **LLM(Bedrock) 사용 안 함** — 규칙 기반 추출 + 칩 선택 |
| 로그인·가입 화면 | 별도 `login.html`/`signup.html`/`account.html` 페이지(2026-09-11 멀티페이지 전환 후). 화면 코드는 `frontend/js/pages/auth.js` |
| 프론트 구조 | 해시 라우트 1개 HTML(`TrueFit.html`) → **화면마다 별도 `.html` 파일**로 전환(2026-09-11). 화면 지도·페이지별 파일은 `frontend/CLAUDE.md` 참고. URL도 `#/results` 같은 해시가 아니라 `results.html`처럼 실제 경로다 — 백엔드에서 프론트 화면 링크를 만들 일이 있으면 이 점을 참고 |

> **해커톤 시연 가능 여부는 아래 "해커톤 전" 항목의 백엔드 완료에 달려 있다.** 프론트는 계약대로 호출 코드를 먼저 만들고, API가 준비되는 순서대로 실제 동작을 확인한다.

## 요청 목록

| 구분 | 내용 | 담당 영역 | 시급도 |
|---|---|---|---|
| A | 회원 인증: `app_user` 컬럼 추가 + 인증 API 8개 | DB·백엔드 | **해커톤 전** |
| B | DB 개발 환경 (Docker 설치 안내, 공용 개발 DB 여부) | 인프라·전원 | **즉시** |
| C | 데이터 적재: PC 부품·가격·리뷰 요약, 유아용품 상품 | 백엔드·데이터 | **해커톤 전** |
| D | 세션·채팅·추천·장바구니·리포트 API (규칙 기반 조건 추출, PC·유아) | 백엔드 | **해커톤 전** |
| E | 프론트 서빙·CORS·배포 | 백엔드·인프라 | **해커톤 전** |
| F | 문서 정리 | 문서 | 해커톤 전 |
| G | 10월까지 추가 작업 | 백엔드 | 10월 |

---

## A. 회원 인증: 이메일 + 비밀번호

### A-1. 결정 사항

- 기획서 §3의 "이메일 6자리 코드 로그인(비밀번호 없음)"을 **이메일 + 비밀번호 로그인**으로 바꾼다.
- 로그인은 **DB `identity.app_user`에 저장된 계정만** 통과한다.
- 회원가입 화면에서 받는 값: 이메일, 비밀번호(영문+숫자 포함 8자 이상), 표시 이름, [필수] 이용약관 동의, [필수] 개인정보 처리방침 동의, [선택] 마케팅 수신 동의.
- 해커톤까지는 **이메일 인증 없이 가입 즉시 로그인**한다(이메일 인증은 10/26, §G).
- 회원정보 화면: 표시 이름·이메일·마케팅 동의 수정, 비밀번호 변경, 로그아웃, 회원 탈퇴.
- 비밀번호·약관 동의 정보는 **새 테이블을 만들지 않고 `identity.app_user`에 컬럼을 추가**한다.
  - 인증 수단이 비밀번호 하나이고 소셜 로그인 계획이 없으므로 조인 없이 한 행에서 처리하는 편이 단순하다.
  - 대신 `password_hash`가 다른 조회에 섞여 나가지 않도록 **repo에서 `SELECT *`를 쓰지 않고**, 사용자 정보를 돌려주는 쿼리에서는 이 컬럼을 뺀다.
  - 나중에 인증 수단이 여러 개가 되면 별도 자격증명 테이블로 분리를 검토한다.

### A-2. DB 변경 — `db/migrations/0007_app_user_password_auth.sql` (신규)

마이그레이션은 forward-only이고 파일명 순서로 적용된다(`db/migrate.py`). `0007` 번호는 `develop`·`rag`·`front` 브랜치 어디에서도 쓰이지 않았다.

```sql
-- 0007: 이메일+비밀번호 인증을 위한 identity.app_user 확장
ALTER TABLE identity.app_user
  ADD COLUMN password_hash        text,
  ADD COLUMN password_updated_at  timestamptz,
  ADD COLUMN failed_login_count   integer NOT NULL DEFAULT 0,
  ADD COLUMN locked_until         timestamptz,
  ADD COLUMN last_login_at        timestamptz,
  ADD COLUMN terms_version        text,
  ADD COLUMN terms_agreed_at      timestamptz,
  ADD COLUMN privacy_agreed_at    timestamptz,
  ADD COLUMN marketing_agreed_at  timestamptz,
  ADD COLUMN deleted_at           timestamptz;

ALTER TABLE identity.app_user
  ADD CONSTRAINT app_user_failed_login_count_check CHECK (failed_login_count >= 0),
  ADD CONSTRAINT app_user_deleted_at_check CHECK ((status = 'deleted') = (deleted_at IS NOT NULL));
```

| 컬럼 | 타입 | NULL | 기본값 | 설명 |
|---|---|:---:|---|---|
| `password_hash` | text | Y | — | argon2id 인코딩 문자열(알고리즘·파라미터·salt 포함). 평문 저장 금지. 탈퇴 시 NULL |
| `password_updated_at` | timestamptz | Y | — | 비밀번호 설정·변경 시각. **이 시각 이전에 발급된 로그인 토큰은 무효** 처리에 사용 |
| `failed_login_count` | integer | N | 0 | 연속 로그인 실패 횟수. 성공 시 0 |
| `locked_until` | timestamptz | Y | — | 실패 누적으로 잠긴 경우 해제 시각 |
| `last_login_at` | timestamptz | Y | — | 마지막 로그인 성공 시각 |
| `terms_version` | text | Y | — | 동의한 약관 버전 (예: `2026-09-11`) |
| `terms_agreed_at` | timestamptz | Y | — | 이용약관 동의 시각 |
| `privacy_agreed_at` | timestamptz | Y | — | 개인정보 처리방침 동의 시각 |
| `marketing_agreed_at` | timestamptz | Y | — | 마케팅 수신 동의 시각. 미동의·철회 시 NULL |
| `deleted_at` | timestamptz | Y | — | 탈퇴 시각. `status='deleted'`와 항상 함께 설정 |

- 약관·비밀번호 컬럼을 NULL 허용으로 둔 이유: 탈퇴 시 개인정보를 지워야 하고, 이후 다른 인증 수단이 생길 여지를 남기기 위해서다. **가입 시 필수 여부는 API에서 검사**한다.
- 기존 컬럼 사용 규칙:
  - `email_normalized` = `lower(trim(email))`. 기존 UNIQUE 제약 그대로 사용.
  - `auth_subject` = `'local:' || <user_id>`. 서비스에서 UUID를 먼저 만들어 `id`와 `auth_subject`에 같이 넣는다.
  - `email_verified_at`: 해커톤에서는 NULL. 이메일 변경 시 NULL로 초기화.
  - `status`: `active` / `suspended` / `deleted` 기존 CHECK 그대로.
- 기존 `updated_at` 갱신 트리거(0004)는 그대로 동작한다. 인덱스 추가는 필요 없다(이메일 UNIQUE 인덱스로 조회).
- 적용 전 확인: 이미 데이터가 있는 DB라면 `status='deleted'`인데 `deleted_at`이 없는 행이 있으면 두 번째 제약이 실패한다(신규 DB는 해당 없음).
- **`docs/db/table_spec.md` §03 `identity.app_user` 표와 제약 설명도 같이 갱신**해야 한다.

### A-3. 동작 규칙

**회원가입**
1. 이메일 정규화 → 형식 검사 → 이미 있으면 `409 email_taken`.
2. 비밀번호 규칙(8~128자, 영문·숫자 각 1자 이상) 불만족 시 `422 weak_password`.
3. 필수 약관 2개 미동의 시 `422 terms_required`.
4. argon2id로 해시 → `app_user` INSERT(`password_updated_at`, `terms_*`, `privacy_agreed_at`=now, 마케팅 동의 시 `marketing_agreed_at`=now) → `user_preference` 기본 행 INSERT.
5. 비로그인 상태에서 만든 대화·장바구니(`browser_token` 소유)를 새 계정에 병합(기획 §3-3 6번 유지).
6. 가입 직후 로그인 상태로 응답한다(로그인 유지 쿠키).

**로그인**
1. 이메일로 `status='active'` 사용자 조회. 없으면 **가짜 해시 검증을 한 번 수행한 뒤** `401 invalid_credentials` (응답 시간으로 가입 여부가 드러나지 않게).
2. `locked_until > now()`이면 `423 account_locked`.
3. 비밀번호 불일치 → `failed_login_count + 1`. 5회 도달 시 `locked_until = now() + 15분`, 횟수 0으로 초기화 → `401 invalid_credentials`.
4. 성공 → `failed_login_count=0`, `locked_until=NULL`, `last_login_at=now()`. argon2 파라미터가 바뀌어 재해시가 필요하면 해시 갱신. 비로그인 데이터 병합. 토큰 쿠키 발급.

**로그인 상태 확인 (인증이 필요한 모든 요청)**
- 쿠키의 JWT 서명·만료 확인 → 사용자 조회 → `status='active'`인지 확인.
- `iat`(초 단위 정수) `>= floor(extract(epoch from password_updated_at))`인지 확인. 비밀번호 변경·탈퇴 전에 발급된 토큰을 막는다. **초 단위로 내림해서 비교**해야 변경 직후 발급한 토큰이 거부되지 않는다.

**비밀번호 변경**
- 현재 비밀번호 확인(틀리면 `401 invalid_password`) → 새 비밀번호 규칙 검사 → 해시·`password_updated_at` 갱신 → **새 토큰 쿠키 재발급**(기존 토큰은 위 규칙으로 무효).

**회원정보 수정**
- 표시 이름(1~20자), 이메일(변경 시 중복 검사 `409 email_taken`, `email_verified_at=NULL`), 마케팅 동의(동의 시 now, 철회 시 NULL).

**회원 탈퇴 (소프트 삭제 + 개인정보 제거)**
- 다른 테이블의 FK가 모두 `ON DELETE RESTRICT`라 행을 물리 삭제할 수 없다. 명세서의 "참조를 유지하는 익명 계정 처리" 방침에 따라 아래처럼 처리한다.
- 요청 시 **현재 비밀번호 확인 필수**(틀리면 `401 invalid_password`).

```sql
UPDATE identity.app_user
SET status = 'deleted',
    deleted_at = now(),
    email_normalized = 'deleted+' || id::text || '@deleted.invalid',
    display_name = '탈퇴한 사용자',
    password_hash = NULL,
    password_updated_at = now(),
    email_verified_at = NULL,
    marketing_agreed_at = NULL,
    failed_login_count = 0,
    locked_until = NULL
WHERE id = %(user_id)s AND status = 'active';

UPDATE identity.user_preference
SET ui_settings = '{}'::jsonb, notification_settings = '{}'::jsonb
WHERE user_id = %(user_id)s;
```

- 이메일을 익명 값으로 바꾸므로 **같은 이메일로 즉시 재가입할 수 있다.** 재가입 제한 기간이 필요하면 별도 결정(§G).
- 탈퇴 회원의 장바구니·리뷰·가격 알림 처리(삭제/익명 유지/알림 중지)는 §G에서 정책을 정한다. 최소한 **가격 알림 발송 대상에서 제외**해야 한다.
- 응답 시 로그인 쿠키 삭제.

### A-4. API 계약 (프론트 `TF_AUTH`와 1:1 대응)

- 모든 요청·응답은 JSON. 오류는 기존 봉투 형식 `{"error": {"code", "message", "field"}}` (`src/errors.py`).
- 인증 토큰은 **httpOnly 쿠키**로 주고받는다. 프론트는 토큰을 읽거나 저장하지 않는다.
  - 쿠키 이름 `truefit_session`, `HttpOnly`, `SameSite=Lax`, `Path=/`, 운영(https)에서는 `Secure`.
  - 로그인 상태 유지 체크 시 `Max-Age` = `JWT_TTL_DAYS`(14일). 미체크 시 브라우저 세션 쿠키 + JWT 만료 12시간.
  - 프론트와 API를 같은 도메인에서 서빙하거나, 개발 중 다른 포트라면 CORS 설정이 필요하다(§E).

사용자 객체 `User`:

```json
{ "id": "uuid", "email": "you@example.com", "display_name": "홍길동", "marketing_agreed": false, "created_at": "2026-09-11T07:00:00Z" }
```

| 프론트 `TF_AUTH` | 메서드·경로 | 요청 본문 | 성공 응답 | 주요 오류 코드 |
|---|---|---|---|---|
| `signup` | `POST /auth/signup` | `{email, password, display_name, terms_agreed, privacy_agreed, marketing_agreed}` | `201 {user}` + 쿠키 | `email_taken`(409), `weak_password`(422), `terms_required`(422), `validation_failed`(422) |
| `login` | `POST /auth/login` | `{email, password, remember}` | `200 {user}` + 쿠키 | `invalid_credentials`(401), `account_locked`(423), `rate_limited`(429) |
| `logout` | `POST /auth/logout` | — | `204` + 쿠키 삭제 | — |
| `me` | `GET /auth/me` | — | `200 {user}` | `unauthorized`(401) |
| `updateProfile` | `PATCH /auth/me` | `{display_name?, email?, marketing_agreed?}` | `200 {user}` | `email_taken`(409), `validation_failed`(422), `unauthorized`(401) |
| `changePassword` | `POST /auth/password` | `{current_password, new_password}` | `204` + 새 쿠키 | `invalid_password`(401), `weak_password`(422) |
| `withdraw` | `POST /auth/withdraw` | `{password}` | `204` + 쿠키 삭제 | `invalid_password`(401) |
| `checkEmail` | `GET /auth/email-availability?email=` | — | `200 {available: bool}` | `validation_failed`(422), `rate_limited`(429) |

- `checkEmail`은 가입 화면의 실시간 중복 확인용이다. 가입 여부를 조회할 수 있게 되므로 **IP당 요청 제한**(예: 분당 30회, 데모는 인메모리)을 둔다.
- 탈퇴를 `DELETE`가 아니라 `POST /auth/withdraw`로 둔 이유: 비밀번호를 본문으로 받아야 하는데, DELETE 본문은 일부 프록시·클라이언트에서 누락될 수 있다.
- 기존 `POST /auth/request-code`, `POST /auth/verify`는 이번 흐름에서 쓰지 않는다. **삭제하지 말고 보류**한다(비밀번호 재설정·이메일 인증에 재사용 예정, §G).

### A-5. 수정 대상 파일

| 파일 | 변경 |
|---|---|
| `db/migrations/0007_app_user_password_auth.sql` | **신규** — §A-2 SQL |
| `docs/db/table_spec.md` §03 | 컬럼·제약·탈퇴 규칙 반영 |
| `src/db/__init__.py` | **선행 조건**: 커넥션 풀 `get_pool`/`get_conn` 구현 (현재 미구현 — §C·§D도 이게 있어야 동작) |
| `src/auth/passwords.py` | **신규** — `hash_password`, `verify_password`, `needs_rehash` (argon2-cffi) |
| `src/auth/jwt.py` | `issue`/`verify` 구현 (PyJWT, HS256, `JWT_SECRET`, 클레임 `sub`, `iat`, `exp`) |
| `src/auth/deps.py` | 쿠키 → JWT → 사용자 상태·`password_updated_at` 검사 (`current_user`, `optional_principal`) |
| `src/repo/user_repo.py` | `create_local_user`, `get_for_login`(해시 포함), `get`(해시 제외), `record_login_success/failure`, `update_profile`, `update_password`, `withdraw`, `is_email_taken` |
| `src/services/auth_service.py` | `signup`, `login`, `logout`, `update_profile`, `change_password`, `withdraw`, 비로그인 데이터 병합 |
| `src/schemas.py` | `SignupIn`, `LoginIn`, `UserOut`, `ProfilePatchIn`, `PasswordChangeIn`, `WithdrawIn`, `EmailAvailabilityOut` |
| `src/routers/auth.py` | §A-4 엔드포인트 추가·구현 (`request-code`/`verify`는 보류) |
| `src/errors.py` | `AccountLocked`(`account_locked`, 423) 추가. 나머지 코드는 기존 클래스에 `code` 지정 |
| `src/config.py` | `COOKIE_NAME`, `COOKIE_SECURE`, `SESSION_TTL_HOURS`(12), `LOGIN_MAX_FAILURES`(5), `LOGIN_LOCK_MINUTES`(15), `TERMS_VERSION` |
| `requirements.txt`, `pyproject.toml`, `uv.lock` | `argon2-cffi`, `PyJWT`, `psycopg-pool` 추가 (현재 셋 다 없음) |
| `.env.example` | `JWT_SECRET`(운영 필수, 기본값 사용 금지), `COOKIE_SECURE` |
| `tests/test_auth.py` | **신규** — 가입·중복·로그인 실패 잠금·비밀번호 변경 후 이전 토큰 거부·탈퇴 후 로그인 불가·재가입 |

---

## B. DB 개발 환경

| 항목 | 내용 |
|---|---|
| 현상 | Windows에서 `db/README.md` 절차대로 `docker compose up -d db` 실행 시 `'docker' 용어가 ... 인식되지 않습니다` 오류. Docker Desktop이 설치되지 않은 PC에서는 DB를 띄울 수 없다 |
| 요청 1 | `db/README.md`에 **사전 준비** 추가: Docker Desktop 설치(Windows는 WSL2 엔진), 설치 후 새 터미널에서 `docker version` 확인, 5432 포트 충돌 시 대처 |
| 결정 (2026-09-11) | **공용 개발 DB 없음. 각자 로컬 Docker DB** 사용, 이후 AWS 배포 시 공용 DB 구성 |
| 요청 2 | 각자 DB가 다르므로 **§C 적재 스크립트로 누구나 같은 데이터를 재현**할 수 있어야 한다. 새 마이그레이션·적재 스크립트가 추가되면 실행 순서(`migrate.py up` → 적재)를 `db/README.md`에 적는다 |
| 요청 3 | Windows 설치 직후 IDE 터미널에서 `docker`를 못 찾는 경우 안내: Docker Desktop이 사용자 경로(`%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin`)에 설치되어, **IDE를 완전히 재시작**해야 PATH가 반영된다 |

---

## C. 데이터 적재 (해커톤 전)

현재 DB에 INSERT하는 코드는 RAG(`src/repo/rag_repo.py`, `scripts/rag_manual.py`)뿐이다. **채팅·추천이 참고할 `catalog`·`evidence`·`community` 테이블은 비어 있다.**

| 데이터 | 원본 | 대상 테이블 | 현황·문제 |
|---|---|---|---|
| PC 부품 | `data/parts_list.csv`, `data/parts_specs.json` | `catalog.product`, `product_variant`, `product_category(_membership)`, `product_fact` | 적재 코드 없음. 현재 엔진(`src/repo/catalog_repo.py`)은 CSV를 직접 읽고 **가격·성능 등급을 이름 해시로 만든 값**으로 채움 |
| PC 가격·판매처 | 없음 (합성 필요) | `catalog.merchant`, `offer`, `offer_observation` | 생성기(`gen_parts_offers.py`)는 기획서에만 있고 코드 없음 |
| PC 리뷰 요약 | `data/review_summaries.json` | `evidence.review_summary`, `review_aggregate` 등 | 적재 코드 없음 |
| 유아용품 상품 | `scripts/generate_baby_products.py` 출력 | `catalog.*` | **생성기 기본 입력 `scripts/유아용품_가상제품_스펙사전_v1.json`이 어떤 브랜치·커밋에도 없음** → 파일 작성자가 커밋해야 생성 가능 |
| 유아용품 설명서 | `generated/synthetic_manuals/`, RAG | `assets.*`, `rag.*` | RAG 적재는 관리자 CLI로 구현됨 |
| 유아용품 카테고리 정의 | `config/categories/baby.yaml` | — | `status: stub`, `question_sets: []` — 채팅 질문·칩 정의 필요 |

- 요청: **적재 스크립트**(예: `scripts/seed_catalog.py`) — 새 DB에서 한 번에 재현, 여러 번 실행해도 중복되지 않게(멱등).
- 합성 데이터는 출처(`evidence.source` 등)에 합성임을 기록한다. 화면은 이 값을 근거로 "예시 데이터" 표시를 한다.

---

## D. 세션·채팅·추천·장바구니·리포트 API (해커톤 전)

### D-1. 현황
- `/session/*`, `/lists/*`, `/reviews/*` 전부 501. 서비스·repo 미구현.
- 엔진 파이프라인은 **시나리오 파일 입력만** 받는다: [1] 조건 추출은 시나리오 정답 주입, [3-0] 후보는 CSV, [3-C] 검증 점수는 시나리오 주입. 유아용품 분기(`per_item`)와 [3-0] 유아 후보는 `NotImplementedError`.

### D-2. 필요한 동작

| 화면 | 필요한 동작 | 관련 API |
|---|---|---|
| 카테고리 선택 | 대화·계획 생성(`identity.conversation`, `planning.plan`), 카테고리·모드 확정, 슬롯 구조·필수 입력·질문 칩 반환 | `POST /session`, `POST /session/{id}/category` |
| 조건 대화 | 메시지 저장(`identity.message`). **LLM 없이 규칙 기반 조건 추출**: 칩 선택은 `question_sets.maps_to`로 직접 반영, 자유 입력은 규칙(예산 금액 "150만원", 용도·해상도 키워드, 월령 "6개월", 품목명 사전 등). 추출 못 한 조건은 `next_questions` 칩으로 되묻기(기획 §2-2 파싱 실패 대비) | `POST /session/{id}/message`, `/answer`, `PATCH /session/{id}/slot` |
| 추천 실행·결과 | 조건 → [2]~[5] 실행. **[3-0] 후보는 DB `catalog`에서 조회**, 시나리오 의존 제거. PC는 세트 구성, 유아용품은 품목별 추천 + 예산·구매 시점 배분. 결과 저장(`engine.recommendation_run`, `recommendation_candidate`) | `POST /session/{id}/recommend`, `GET /session/{id}/result` |
| 추천 과정 보기 | 단계별 로그(`reasoning_log`) | `GET /session/{id}/result` |
| 장바구니 담기·수량·구매 시점 | 결과 화면 오른쪽 장바구니의 담기/빼기, 수량 ±, 유아용품 구매 시점 | **신규** `PATCH /session/{id}/items/{item_id}` |
| 후보 교체 | 결과 화면의 "후보 교체"로 슬롯의 다른 후보 비교·선택 | **신규** `GET /session/{id}/items/{item_id}/alternatives`, `POST .../swap` |
| 리뷰·근거 상세 | 정제 전후 평점·평점 분포·요약·출처 | `GET /reviews/summary/{product_key}` |
| 결과 화면 대화 | "그래픽카드를 더 저렴한 걸로" 같은 요청을 규칙 기반으로 해석해 후보 교체 | **신규** `POST /session/{id}/result-message` |
| 대화 다시 시작·사양 파일 | 조건 대화 초기화, 업그레이드 모드 사양 파일 인식 | **신규** `POST /session/{id}/reset`, `POST /session/{id}/spec-file` |

요청·응답 필드는 **§D-4 계약 초안**을 따른다.
| 리스트 확정·리포트·가격 알림 | 이름·구매 예정일·목표가 저장, 리포트 조회, 알림 설정 | `POST /lists/{id}/confirm`, `GET /lists/{id}/report`, `POST /lists/{id}/alert` |
| 사이드바 장바구니 | 목록, **이름 변경, 삭제** | `GET /lists`, **신규** `PATCH /lists/{id}`, `DELETE /lists/{id}` |

### D-3. LLM 사용 범위 (확정 2026-09-11)
| 단계 | LLM | 비고 |
|---|---|---|
| [1] 채팅 조건 추출 | **사용 안 함** | 규칙 기반 + 칩 선택 |
| [3-C] 검증 쟁점 문장 | **사용** | 기획서 기준 Bedrock Claude Haiku. 시나리오 주입 제거 |
| [5] 추천 설명 문장 | **사용** | 〃 |

- `src/clients/llm_client.py`의 실제 호출(현재 `MOCK_MODE=0`이면 `NotImplementedError`)을 구현해야 한다.
- 각자 로컬 DB로 개발하므로, LLM을 호출하는 개발자 PC마다 **AWS 자격증명·리전·Bedrock 모델 접근 권한**이 필요하다. 설정 방법을 `README.md`나 `.env.example`에 정리한다.
- LLM 호출 실패·지연 시 결과 응답이 멈추지 않도록, 추천 결과는 먼저 저장·반환하고 문장 필드는 `pending`/`failed` 상태로 구분하는 방식을 권장한다(화면은 상태에 따라 "설명 생성 중"/"설명을 만들지 못했습니다" 표시).

### D-3-1. 아직 결정 필요
- **[3-C] 검증 근거**: `product_fact` 기반 규칙 검사(소켓·메모리 규격·전력 여유 등) 결과를 LLM이 문장화할지, LLM이 근거 문서(RAG)까지 직접 판단할지.
- 결과 조회 방식: 폴링(`GET /result`) 확정 여부 (기획 §18-1). LLM 문장 생성이 늦을 수 있어 폴링을 권장.

### D-4. API 계약 초안 (2026-09-11 · 프론트 작성 · **백엔드 검토 후 확정**)

`src/schemas.py`의 `SessionOut`, `ConditionStateOut`, `RecommendResultOut`, `ReportOut` 등은 골격만 있어 아래 내용으로 교체·확장이 필요하다. 필드 이름·구조를 바꿔야 하면 이 문서를 먼저 고친 뒤 구현한다.

#### D-4-0. 프론트 연결 현황과 백엔드 구현 체크리스트

프론트는 2026-09-11 현재 아래 파일에서 이 계약의 요청 경로와 응답 필드를 사용한다.

| 프론트 파일 | 담당 범위 |
|---|---|
| `frontend/js/api.js` | `TF_API` 공통 fetch, `TF_AUTH`, 오류 봉투 처리 |
| `frontend/js/core.js` | `TF_PLAN` API 어댑터, 장바구니 목록·공통 상태 |
| `frontend/js/pages/planner.js` | 세션 생성, 카테고리, 조건 대화, 칩 답변, 조건 수정, 초기화, 사양 파일 |
| `frontend/js/pages/results.js` | 추천 결과·폴링, 후보 교체, 리뷰, 확정, 리포트, 가격 알림 |
| `frontend/js/app.js` | 화면 이벤트를 위 API 어댑터에 연결 |

프론트에는 가짜 응답 fallback이 없다. 따라서 아래 항목이 구현되기 전에는 화면 연결 코드를 작성했더라도 실제 사용자 흐름을 완료할 수 없다.

- `src/routers/session.py`: `GET /session/{list_id}`, `/reset`, `/spec-file`, `/items/{item_id}`, `/alternatives`, `/swap`, `/result-message`를 추가한다.
- `src/routers/lists.py`: `PATCH /lists/{list_id}`, `DELETE /lists/{list_id}`를 추가한다.
- `src/schemas.py`: 현재 골격을 아래 `ConditionState`, `RecommendResult`, `ListSummary`, `Report`, `PriceWatch` 구조로 교체한다.
- `SessionOut.browser_token`을 제거하고 `truefit_guest` httpOnly 쿠키로 전달한다.
- `POST /session/{list_id}/recommend`는 선택적인 `strategy` 본문을 받고 `202 {"run_id", "status"}`를 반환하도록 바꾼다. 현재 라우터 선언은 본문을 받지 않고 `RecommendResultOut`을 즉시 반환하는 형태다.
- `ConfirmIn`에 `memo`를 추가하고, 가격 알림에는 `{"enabled", "target_amount"?}` 전용 입력 스키마를 사용한다.
- `GET /lists`는 배열 자체가 아니라 `{"items": [ListSummary]}`를 반환한다.
- 모든 구현은 `credentials: include`로 전달되는 로그인 쿠키와 guest 쿠키를 모두 고려하고, 아래 공통 오류 봉투를 유지한다.

**프론트-백엔드 통합 완료 기준**

1. 비로그인 상태에서 세션 생성 → PC·유아용품 조건 대화 → 추천 결과 조회까지 완료된다.
2. 결과에서 담기·빼기, 수량, 구매 시점, 후보 교체, 결과 대화가 새로고침 후에도 서버 상태로 복원된다.
3. 비로그인 확정 시 401을 받고 로그인 화면으로 이동하며, 로그인 후 같은 `list_id`의 `#/confirm`으로 돌아온다.
4. 확정 후 `GET /report`의 데이터만으로 리포트를 그리고, 알림 설정·목록 이름 변경·삭제가 서버에 반영된다.
5. API 미구현 시 501 `not_implemented`, 입력 오류 시 422 계약 오류, 소유권 불일치 시 404 `not_found`가 공통 봉투로 반환된다.

**공통 규칙**
- JSON, 오류 봉투 `{"error": {"code", "message", "field"}}`. 금액은 원 단위 정수, 시각은 ISO 8601(UTC), 날짜는 `YYYY-MM-DD`.
- 카테고리 값은 `computer` | `baby`.
- **비로그인 소유권**: `POST /session` 응답에서 httpOnly 쿠키 `truefit_guest`(browser_token)를 발급한다. 본문으로 토큰을 돌려주지 않는다(현재 `SessionOut.browser_token` 제거). 로그인·가입 시 이 쿠키 소유 데이터를 계정에 병합(§A-3).
- 리스트 접근은 소유자(로그인 사용자 또는 guest 쿠키)만 가능하다. 소유자가 아니면 존재 여부를 숨기기 위해 `404 not_found`.
- 화면에 보이는 한국어 표시 문자열(`label`, `display`, 질문·답변 문장)은 서버가 준다. 프론트는 그대로 표시하고 영문 전환만 자체 사전으로 처리한다.
- LLM이 만드는 문장 필드는 `{"status": "pending" | "ready" | "failed", "text": ...}` 형태로 준다(§D-3).

#### D-4-1. 조건 대화

**`ConditionState`** — 조건 대화 API의 공통 응답

```json
{
  "list_id": "uuid",
  "category": "computer",
  "messages": [
    {"id": "uuid", "role": "user", "text": "게임용 컴퓨터를 새로 맞추고 싶어요", "created_at": "2026-09-11T08:00:00Z"},
    {"id": "uuid", "role": "assistant", "text": "예산은 얼마까지 생각하시나요?", "created_at": "2026-09-11T08:00:01Z"}
  ],
  "fields": [
    {"key": "mode", "label": "구성 방식", "value": "build", "display": "새 컴퓨터", "status": "confirmed", "editable": true},
    {"key": "purpose", "label": "주요 용도", "value": "game", "display": "게임", "status": "confirmed", "editable": true},
    {"key": "budget_max", "label": "예산", "value": null, "display": null, "status": "missing", "editable": true}
  ],
  "next_question": {
    "id": "q_budget_max", "field": "budget_max", "text": "예산은 얼마까지 생각하시나요?",
    "select": "free", "options": []
  },
  "can_recommend": false,
  "accepts_spec_file": false
}
```

- `fields[].status`: `confirmed` | `assumed` | `missing`. 화면 오른쪽 "선택한 조건 확인" 패널이 `fields` 순서대로 그린다.
- `next_question.select`: `single` | `multi` | `free`. `options`는 `[{"value", "label"}]` — 칩으로 표시한다. 조건이 모두 차면 `null`.
- `accepts_spec_file`: 업그레이드 모드에서 사양 파일 첨부 버튼 표시 여부.

**카테고리별 필드** (화면 요약 패널 순서 그대로)

| 카테고리 | key | label | value 형식 | 필수 |
|---|---|---|---|---|
| computer | `mode` | 구성 방식 | `build` \| `upgrade` | ✓ |
| computer | `spec_file_name` | 첨부 사양 파일 | 문자열 | upgrade일 때 표시 |
| computer | `current_specs` | 현재 사양 | `{"CPU": "...", "GPU": "...", "RAM": "..."}` | upgrade일 때 ✓ |
| computer | `upgrade_parts` | 업그레이드 부품 | `["GPU", "RAM"]` | upgrade일 때 ✓ |
| computer | `purpose` | 주요 용도 | `game` \| `creation` \| `office` \| `study` \| `other` (+ `display`에 사용자 표현) | ✓ |
| computer | `budget_max` | 예산 | 정수(원) | ✓ |
| computer | `priority` | 우선순위 | `performance` \| `value` \| `quiet` | ✓ |
| baby | `age_stage` | 아이 연령대 | `{"months": 8 \| null, "label": "이유식기"}` | ✓ |
| baby | `needs` | 필요한 영역 | `["수유", "이유식·식사", "수면", "외출", "목욕·위생", "기저귀·배변", "의류", "놀이", "안전·건강"]` 중 복수 | ✓ |
| baby | `health_skin` | 건강·피부 특성 | `["아토피", "민감성 피부"]` 또는 `["none"]`(특이사항 없음) | ✓ |
| baby | `owned_items` | 이미 보유한 물품 | `["유모차", "젖병"]` 또는 `["none"]`(없음) | ✓ |
| baby | `budget_max` | 예산 | 정수(원) | ✓ |

- "몰라요"·"모르겠어요" 같은 답은 값으로 받지 않고 `missing`으로 남겨 다시 묻는다(현재 화면 규칙과 동일).
- `config/categories/computer.yaml`·`baby.yaml`의 `slot_schema`·`required_inputs`·`question_sets`를 위 필드에 맞게 갱신해야 한다. 현재 yaml에는 `priority`, `upgrade_parts`, `current_specs`, `needs`, `health_skin`, `owned_items`, `age_stage`가 없고, baby는 `question_sets: []`이다.

| 화면 동작 | 메서드·경로 | 요청 본문 | 성공 응답 | 주요 오류 |
|---|---|---|---|---|
| 새 장바구니 만들기 | `POST /session` | — | `201 {"list_id"}` (+ 비로그인이면 `truefit_guest` 쿠키) | — |
| 조건 대화 화면 다시 열기 (새로고침·사이드바에서 선택) | `GET /session/{list_id}` (**신규**) | — | `200 ConditionState` (카테고리 미선택이면 `category: null`) | `not_found`(404) |
| 카테고리 선택·변경 | `POST /session/{list_id}/category` | `{"category"}` | `200 ConditionState` (첫 안내 메시지 포함). 변경 시 기존 조건·결과 초기화 | `validation_failed`(422) |
| 채팅 입력 | `POST /session/{list_id}/message` | `{"text"}` (500자 이하) | `200 ConditionState` (사용자·답변 메시지 추가). 조건이 다 찬 뒤 입력은 조건 변경으로 반영하고, 반영할 게 없으면 메모로 저장 | `category_required`(409) |
| 질문 칩 선택 | `POST /session/{list_id}/answer` | `{"question_id", "selected": ["value"]}` | `200 ConditionState` | `validation_failed`(422) |
| 요약 패널 조건 수정 | `PATCH /session/{list_id}/slot` | `{"field", "value": null}` | `200 ConditionState` (해당 조건을 다시 질문, 기존 추천 결과 무효화) | `validation_failed`(422) |
| 대화 다시 시작 | `POST /session/{list_id}/reset` (**신규**) | — | `200 ConditionState` (카테고리 유지, 조건·대화·결과 초기화) | — |
| 업그레이드 사양 파일 첨부 | `POST /session/{list_id}/spec-file` (**신규**) | `{"file_name", "content"}` (텍스트, 1MB 이하, txt·json·csv·md·log·nfo·xml) | `200 ConditionState` (`current_specs`·`spec_file_name` 반영) | `file_too_large`(413), `unsupported_file`(422) |

> **결정 필요 — 사양 파일**: 현재 디자인 문구는 "첨부 파일은 이 브라우저 안에서만 읽으며 외부로 전송하지 않습니다"이다. 위 계약처럼 서버에서 사양을 추출하면 **문구를 "사양 인식을 위해 파일 내용을 서버로 전송합니다"로 바꿔야 한다.** 조건 추출 규칙을 서버 한 곳에 모으기 위해 서버 추출을 권장한다.

#### D-4-2. 추천 실행과 결과

| 화면 동작 | 메서드·경로 | 요청 본문 | 성공 응답 | 주요 오류 |
|---|---|---|---|---|
| "이 조건으로 추천 보기" | `POST /session/{list_id}/recommend` | `{}` | `202 {"run_id", "status": "running"}` | `conditions_incomplete`(422), `run_in_progress`(409) |
| "다른 구성 보기" | `POST /session/{list_id}/recommend` | `{"strategy": "alternative"}` (현재 구성과 다른 후보 우선) | `202` | 〃 |
| 결과 화면 (1~2초 폴링) | `GET /session/{list_id}/result` | — | `200 RecommendResult` | `not_found`(404, 실행 전) |
| 장바구니 담기·빼기, 수량, 구매 시점 | `PATCH /session/{list_id}/items/{item_id}` (**신규**) | `{"selected"?, "qty"? (1~99), "timing"? ("now" \| "soon" \| "later")}` | `200 RecommendResult` | `validation_failed`(422) |
| 후보 교체 창 | `GET /session/{list_id}/items/{item_id}/alternatives` (**신규**) | — | `200 {"items": [Alternative]}` | `not_found`(404) |
| 후보 선택 | `POST /session/{list_id}/items/{item_id}/swap` (**신규**) | `{"candidate_id"}` | `200 RecommendResult` | `not_found`(404) |
| 결과 화면 채팅 ("그래픽카드를 더 저렴한 걸로") | `POST /session/{list_id}/result-message` (**신규**) | `{"text"}` (300자 이하) | `200 {"reply", "result": RecommendResult}` — 규칙 기반 해석, LLM 미사용 | `validation_failed`(422) |
| 리뷰·근거 상세 | `GET /reviews/summary/{product_key}` | — | `200 ReviewSummary` | `not_found`(404) |

**`RecommendResult`**

```json
{
  "list_id": "uuid",
  "run_id": "uuid",
  "status": "running",
  "progress": [
    {"step": "conditions", "label": "조건 정리", "status": "done"},
    {"step": "candidates", "label": "후보 수집", "status": "running"}
  ],
  "category": "computer",
  "conditions_summary": "게임 · 예산 1,500,000원 · 성능 우선",
  "budget_max": 1500000,
  "items": [
    {
      "item_id": "uuid",
      "slot": "GPU",
      "slot_label": "그래픽카드",
      "product": {
        "product_key": "rtx-4060",
        "variant_id": "uuid",
        "name": "GeForce RTX 4060 8GB",
        "brand": "NVIDIA",
        "spec_summary": "8GB GDDR6 · TDP 115W",
        "image_url": null,
        "purchase_url": null
      },
      "price": 330000,
      "price_source": "synthetic",
      "price_observed_at": "2026-09-11T00:00:00Z",
      "qty": 1,
      "selected": true,
      "timing": "now",
      "budget_share": 0.22,
      "review": {"total_count": 1284, "excluded_ratio": 0.12, "rating_refined": 4.2},
      "reason": {"status": "ready", "text": "QHD 게임 기준 예산 안에서 성능 여유가 가장 큰 후보입니다."},
      "checks": {"status": "pending", "text": null},
      "alternatives_count": 2
    }
  ],
  "totals": {"selected_price": 1420000, "selected_units": 8, "budget_remaining": 80000, "over_budget": false},
  "verification": {
    "status": "ready",
    "confidence": 86,
    "issues": [{"axis": "전력 여유", "severity": "minor", "text": "..."}]
  },
  "explanation": {"status": "pending", "headline": null, "text": null},
  "reasoning_log": [{"step": "01", "title": "조건 정리", "detail": "카테고리 컴퓨터, 예산 1,500,000원"}],
  "data_notice": "상품·가격·리뷰는 합성 데이터입니다."
}
```

- `status`: `running` | `done` | `failed`. `failed`이면 `"error": {"code", "message"}`를 함께 준다(화면에 `message` 표시). 상품·가격이 준비되면 `done`으로 응답하고, LLM 문장(`reason`, `checks`, `verification`, `explanation`)은 각자 `pending`에서 `ready`/`failed`로 바뀐다. 프론트는 `pending`이 남아 있는 동안 폴링을 계속한다.
- `price_source`: `synthetic`(합성) | `observed`(판매처 수집). `review`가 없으면 `null`(리뷰 없음 표시).
- `timing`, `budget_share`: 유아용품 결과의 "예산과 구매 시점" 표에 사용. 컴퓨터는 `timing="now"`.
- `purchase_url`이 `null`이면 "상품 페이지" 버튼은 "판매처 미연결"로 표시한다.
- `item_id`는 결과 안에서 슬롯 한 줄을 가리키는 고정 ID. 후보 교체 후에도 같은 `item_id`를 유지한다.

**`Alternative`** — 후보 교체 창의 카드

```json
{"candidate_id": "uuid", "label": "절약형 후보", "current": false,
 "product": {"product_key": "rtx-3060", "name": "GeForce RTX 3060 12GB", "brand": "NVIDIA", "spec_summary": "12GB GDDR6", "image_url": null},
 "price": 290000, "price_delta": -40000, "review": {"total_count": 932, "excluded_ratio": 0.09, "rating_refined": 4.4}}
```

**`ReviewSummary`** — 리뷰·근거 상세 창

```json
{
  "product_key": "rtx-4060",
  "total_count": 1284,
  "excluded_count": 154,
  "excluded_ratio": 0.12,
  "rating_raw": 4.6,
  "rating_refined": 4.2,
  "distribution_raw": {"5": 0.74, "4": 0.25, "3": 0.11, "2": 0.06, "1": 0.04},
  "distribution_refined": {"5": 0.66, "4": 0.21, "3": 0.07, "2": 0.04, "1": 0.02},
  "summaries": [{"text": "QHD 게임에서 발열이 안정적이라는 평가가 많습니다.", "source": "합성 리뷰 요약", "observed_at": "2026-09-01"}],
  "data_notice": "합성 리뷰 데이터입니다."
}
```

#### D-4-3. 장바구니 목록 · 확정 · 리포트 · 가격 알림

| 화면 동작 | 메서드·경로 | 요청 본문 | 성공 응답 | 주요 오류 |
|---|---|---|---|---|
| 사이드바 "내 장바구니" | `GET /lists` | — | `200 {"items": [ListSummary]}` (로그인 사용자 또는 guest 쿠키 소유분, 최근 수정순) | — |
| 장바구니 이름 변경 | `PATCH /lists/{list_id}` (**신규**) | `{"name"}` (1~60자) | `200 ListSummary` | `validation_failed`(422) |
| 장바구니 삭제 | `DELETE /lists/{list_id}` (**신규**) | — | `204` | `not_found`(404) |
| 리스트 확정 | `POST /lists/{list_id}/confirm` | `{"name", "planned_purchase_at", "target_amount", "memo"}` (memo 1000자 이하) | `200 Report` | `unauthorized`(401 → 프론트가 로그인 화면으로), `no_items_selected`(422), `over_budget`(422) |
| 리포트 | `GET /lists/{list_id}/report` | — | `200 Report` | `unauthorized`(401), `not_found`(404, 미확정) |
| 목표가 알림 설정 | `POST /lists/{list_id}/alert` | `{"enabled", "target_amount"?}` | `200 {"price_watch": PriceWatch}` | `unauthorized`(401) |

**`ListSummary`**

```json
{"list_id": "uuid", "name": "나의 첫 컴퓨터", "category": "computer", "stage": "results", "updated_at": "2026-09-11T08:30:00Z"}
```

- `stage`: `category` | `conditions` | `results` | `report` — 사이드바에서 장바구니를 눌렀을 때 이동할 화면. 이름을 정하지 않았으면 서버가 기본 이름("컴퓨터 장바구니" 등)을 준다.

**`Report`**

```json
{
  "list_id": "uuid",
  "name": "나의 첫 컴퓨터",
  "category": "computer",
  "owner_display_name": "홍길동",
  "planned_purchase_at": "2026-10-01",
  "target_amount": 1400000,
  "memo": "",
  "total": 1420000,
  "confirmed_at": "2026-09-11T09:00:00Z",
  "items": [
    {"slot": "GPU", "slot_label": "그래픽카드",
     "product": {"product_key": "rtx-4060", "name": "GeForce RTX 4060 8GB", "image_url": null, "purchase_url": null},
     "price": 330000, "qty": 1, "timing": "now",
     "review": {"total_count": 1284, "excluded_ratio": 0.12, "rating_refined": 4.2},
     "evidence_text": "QHD 게임 기준 예산 안에서 성능 여유가 가장 큰 후보입니다."}
  ],
  "price_watch": {"enabled": false, "target_amount": 1400000, "status": "waiting", "latest_total": null, "observed_at": null},
  "data_notice": "상품·가격·리뷰는 합성 데이터입니다."
}
```

- `price_watch.status`: `waiting`(추적 대기) | `tracking` | `reached`(목표가 도달). 디자인에 있는 "목표가 도달 예시 보기" 버튼은 가짜 데이터용이라 프론트에서 제거하고 이 값만 표시한다.

#### D-4-4. 참고 — 저장 위치
저장 테이블 선택은 백엔드 설계에 따른다. 화면 기준으로 관련되는 테이블은 `identity.conversation`·`message`(대화), `planning.plan`·`plan_revision`·`plan_condition`·`plan_node`·`purchase_line`(조건·장바구니·확정), `engine.recommendation_run`·`recommendation_candidate`·`validation_result`(추천·검증), `catalog.*`·`evidence.review_*`(상품·리뷰), `notification.price_watch`(알림)이다.

---

## E. 프론트 서빙·CORS·배포 (해커톤 전)

| 대상 | 변경 | 이유 |
|---|---|---|
| `src/api.py` | **둘 중 하나**: (1) API 라우터 등록 뒤 `frontend/`를 정적 파일로 서빙(`StaticFiles`) — 추천, 또는 (2) `CORSMiddleware`(`allow_origins`에 `http://127.0.0.1:5500`, `http://localhost:5500`, `allow_credentials=True`) | 로그인 쿠키를 포함한 API 호출. 현재는 둘 다 없어 브라우저에서 API 호출 불가. 프론트 개발 서버 포트는 **5500** — Windows에서 8080 바인딩이 OS 예약으로 거부되는 사례가 있어 변경(README의 8080 안내도 함께 수정 필요) |
| 정적 서빙 범위 | `frontend/*.html`(랜딩·카테고리·조건 대화·추천 결과·로그·확정·리포트·로그인·회원가입·회원정보 10개), `frontend/css/`, `frontend/js/`, `frontend/assets/`만 공개한다. `frontend/CLAUDE.md` 같은 개발 문서는 제외한다 | 2026-09-11 멀티페이지 전환으로 진입점이 여러 개다. 디자인 원본 HTML은 `frontend/`에 보관하지 않음 |
| `Dockerfile`(신규), `docker-compose.yml` | TrueFit API(+프론트) 컨테이너 추가 | 현재 compose는 DB만 실행, TrueFit용 Dockerfile 없음 |
| 저장소 브랜치 | `origin/backend` 브랜치 내용 확인·정리 | 이 브랜치의 `Dockerfile`·`app/`은 TrueFit이 아닌 다른 프로젝트(Odoo 협상 앱) 코드 |

---

## F. 문서

| 파일 | 변경 | 이유 |
|---|---|---|
| `README.md` | ✅ 완료(프론트에서 처리). 이전 목업 설명 삭제, 멀티페이지 구조·포트 5500·`TF_API` 안내로 갱신 | — |
| `db/README.md` | Docker Desktop 사전 준비 (§B) | 설치 안 된 PC에서 절차 실패 |
| `기술기획서_데모+최종.md` §2-2, §3, §18, §19-1 | 이메일 6자리 코드 → 이메일+비밀번호, JWT 저장 "httpOnly 쿠키" 확정, 조건 추출 LLM 미사용(규칙 기반) | 결정 사항 변경 |
| `프로젝트_기획서_v2.md` 4-3 | 인증 방식 문구 변경 | 결정 사항 변경 |

---

## G. 10월까지 추가 작업

| 항목 | 필요한 화면·기능 | 내용 |
|---|---|---|
| 이메일 인증 (**2026-10-26까지**) | 가입 후 `email_verified_at` | 인증 메일 발송(SES), 인증 전 제한할 기능 결정 |
| 비밀번호 재설정 | 로그인 화면 "비밀번호를 잊으셨나요?" | 기존 `request-code`/`verify` 코드 로직 재사용 → 새 비밀번호 설정 |
| 이메일 변경 시 비밀번호 확인 | 회원정보 수정 | 계정 탈취 방지. 도입 시 `PATCH /auth/me`에 `current_password` 추가 |
| 탈퇴 회원 데이터 정책 | 회원 탈퇴 | 장바구니·리뷰·알림의 삭제/익명 유지 범위, 재가입 제한 기간 |
| 약관 버전 관리 | 약관 개정 시 재동의 | `terms_version` 비교 후 재동의 요청 흐름 |
