# 백엔드 요청 — 회원가입·로그인 API 미구현 (해커톤 전, 시급)

작성일: 2026-09-13 · 작성: 프론트 · 관련: `docs/frontend_외부수정요청.md` §A (이미 등록된 요청 — 아직 미반영 확인용 재전달)

## 증상

CORS 설정 반영 후 `http://127.0.0.1:5500/signup.html`에서 "이메일로 회원가입" 버튼을 클릭하면, 화면에는 아래 오류가 뜬다.

```
서버 기능이 아직 준비 중이에요.
```

같은 시점 백엔드 터미널 로그:

```
INFO:     127.0.0.1:61743 - "POST /auth/signup HTTP/1.1" 404 Not Found
```

**CORS 문제가 아니다.** CORS 차단이면 브라우저 콘솔에 `Access-Control-Allow-Origin` 관련 오류와 `net::ERR_FAILED`가 뜨는데, 이번엔 정상적으로 요청이 서버까지 도달해서 FastAPI가 **경로 자체가 없어서** 404를 반환한 것이다(`TF_API`는 404/501/405를 모두 "서버 기능이 아직 준비 중이에요"로 뭉뚱그려 보여주므로 화면 문구만으로는 구분이 안 된다).

## 원인

`src/routers/auth.py`가 아직 기획서 초안의 **"이메일 6자리 코드" 방식**(`/auth/request-code`, `/auth/verify`, `/auth/logout`, `/auth/me`)만 가지고 있고, 그나마 `verify`/`logout`/`me`도 `raise NotImplementedError`인 뼈대 상태다. 프론트(`frontend/js/api.js`의 `TF_AUTH`)는 **이메일+비밀번호 방식**(`signup`, `login`, `updateProfile`, `changePassword`, `withdraw`, `checkEmail`)으로 호출하도록 이미 구현돼 있다 — 이건 새로 정한 게 아니라 `docs/frontend_외부수정요청.md` §A(2026-09-11 작성)에서 이미 인증 방식을 이메일+비밀번호로 바꾸기로 결정하고 API 8개 계약(§A-4)까지 못박아 둔 항목이다.

직접 코드를 확인해보니 §A-5 "수정 대상 파일" 중:

| 이미 반영된 것 | 아직 반영 안 된 것 |
|---|---|
| `db/migrations/0007_app_user_password_auth.sql` (파일 존재, `password_hash` 등 컬럼 추가) | `src/schemas.py`에 `SignupIn`/`LoginIn`/`UserOut`/`ProfilePatchIn`/`PasswordChangeIn`/`WithdrawIn`/`EmailAvailabilityOut` 없음 |
| `src/db/__init__.py` 커넥션 풀(`get_pool`/`get_conn`, psycopg_pool) 구현됨 | `src/auth/passwords.py` 없음 (argon2 해시) |
| | `src/repo/user_repo.py`의 인증 관련 메서드 없음 |
| | `src/services/auth_service.py`가 여전히 코드 방식(`request_login_code`, `verify_and_issue`)만 있고 `signup`/`login`/`update_profile`/`change_password`/`withdraw` 없음 |
| | `src/routers/auth.py`에 `/auth/signup`, `/auth/login`, `PATCH /auth/me`, `/auth/password`, `/auth/withdraw`, `/auth/email-availability` 없음 |

즉 **DB 스키마와 커넥션 풀은 준비됐지만, 그 위의 서비스·라우터 레이어가 아직 옛날 방식 그대로**라 화면에서 아무 인증 동작도 안 되는 상태다.

## 요청

`docs/frontend_외부수정요청.md` §A-2~§A-5를 그대로 구현해 달라. 새로 정할 내용은 없고, 이미 합의된 계약을 코드로 옮기면 된다. 특히:

1. §A-4의 API 8개 (`signup`/`login`/`logout`/`me`/`updateProfile`/`changePassword`/`withdraw`/`checkEmail`) — 요청·응답 형식, 오류 코드까지 표로 정리돼 있음.
2. §A-3의 동작 규칙 — 특히 로그인 실패 5회 잠금(`423 account_locked`), 비밀번호 변경 시 이전 토큰 무효화(`iat` vs `password_updated_at` 비교), 탈퇴 시 소프트 삭제 SQL은 원인 파악이 어려운 부분이라 문서의 SQL·로직을 그대로 따라야 함.
3. `requirements.txt`/`pyproject.toml`에 `argon2-cffi`, `PyJWT` 추가 필요(§A-5 확인 결과 아직 없음).
4. 기존 `/auth/request-code`, `/auth/verify`는 삭제하지 말고 보류(10월 이메일 인증 재사용 예정, §A-4 마지막 줄).

## 확인 방법

```powershell
uv run uvicorn src.api:app --reload --host 127.0.0.1 --port 8000
```
```powershell
uv run python -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

`http://127.0.0.1:5500/signup.html`에서 이메일·비밀번호(영문+숫자 8자 이상)·표시 이름 입력 후 필수 약관 체크, 가입 버튼 클릭 → `201`과 함께 로그인 상태로 전환되는지 확인. 이어서 로그아웃 → 같은 계정 재로그인 → 회원정보 수정 → 비밀번호 변경 후 새 비밀번호로 로그인 → 탈퇴 후 로그인 불가까지 되면 완료(`frontend/CLAUDE.md`의 확인 흐름 2번과 동일).

## 시급도

**해커톤(2026-09-15) 전 필수.** 회원가입·로그인이 안 되면 로그인 필요 화면(리스트 확정·리포트·회원정보) 전체를 시연할 수 없다.
