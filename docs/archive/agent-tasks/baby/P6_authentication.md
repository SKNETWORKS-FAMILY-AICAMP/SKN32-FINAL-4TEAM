---
task_id: "P6"
status: "develop_alignment_required"
entry_gate: "ready_after_dependencies"
depends_on: ["P1"]
contract_version: 3
report_path: "docs/agent-tasks/baby/reports/P6.md"
---

# P6 — 가입·비밀번호 인증·설정·게스트 인계

## ACTIVE DB CONTRACT — develop `da79839` / v3 (2026-09-13)

이 절과 [develop 전환 계약](DEVELOP_DB_TRANSITION.md), [목표 스키마](schema-v1.md)가 현재 실행 지시다. 이 문서 아래 기존 지시 중 충돌하는 DB 매핑·pgvector 유지·완전 축소 SR 승인 조건은 폐기한다. DB와 무관한 업무 규칙·API·수용 사례는 유지한다. 과거 보고서의 통과 결과는 당시 코드의 증거이며 develop 호환 완료를 뜻하지 않는다. 현재 작업 트리는 `rag`이므로 develop SQL이 이미 병합되어 있다고 가정하지 않는다. `개발 역할 분담`은 적용하지 않는다.

### P6 DELTA — 계정 설정·인증 DB 의존성 정리

- **상태/재사용:** 가입·로그인·게스트 인계의 기존 구현을 재사용하며 DB/토큰 통합 차이만 검증한다. P1의 소유권 경계를 사용한다.
- **EDIT:** `src/repo/user_repo.py`, `src/services/auth_service.py`, `src/auth/{jwt,deps}.py`, 인증 fixture.
- **IMPLEMENT:** ui_settings/notification_settings는 identity.app_user에 저장하고 user_preference SQL을 제거한다. develop JWT의 iat와 비밀번호 변경 시각을 사용하는 무효화 경로에 발급·검증·사용자 조회를 일관되게 연결한다. 이 목표에서는 auth_version 컬럼과0015 의존을 제거하되 비밀번호 변경·탈퇴 후 토큰 거절 보장을 제거하지 않는다. 초 단위 iat 경계에서 같은 초 변경 전 토큰을 거절하고 이후 재로그인 토큰은 정상 사용되는 정책을 구현·문서화한다.
- **IMPLEMENT:** 게스트 인계는 conversation/plan 소유권을 트랜잭션으로 이전한다. planning.item에 대한 소유권 이전 SQL은 제거한다. purchase_line 및 후보는 revision 관계를 따라 접근을 제한한다. develop request-code/verify와 이메일·비밀번호 라우트를 보존한다.
- **ACCEPTANCE D6:** 설정 저장/재로그인 유지, 비밀번호 변경 전 토큰/탈퇴 계정 거절, 변경 후 재로그인 성공(동일 초 포함), 게스트 인계 멱등 및 타 게스트 목록 탈취 차단, user_preference/auth_version 없는 DB에서 실제 인증 왕복.
- **HANDOFF:** develop iat 정책 및 D6 결과를 `reports/P6.md`에 기록한다. 기존 P6 보안 테스트 중 저장 방식과 무관한 결과는 재사용한다.

## PREVIOUS WORK ORDER — non-conflicting business rules only

이하의 날짜별 상태·구 DB 구현 실적은 과거 기록이다. 현재 상태는 위 절과 manifest를 사용한다. 아래 지시에서 완전 축소 SQL 실행, pgvector 보존, planning.item 복원, domain_version/plan_node/purchase_line 삭제, 근거 객체 저장, shared/notification 스키마 삭제를 요구하는 부분은 실행하지 않는다.

## CURRENT BASELINE / SYNC DELTA (2026-09-13)

Read [integration audit](reports/sync-2026-09-13.md); this delta overrides obsolete baseline assumptions below.

- Auth remains unimplemented for password routes. Existing pool/guest cookie from P1 is now live; preserve current Principal entry and route imports.
- Reuse latest public models and app_user staging columns, but do not assume preference migration complete. Tests must include existing cookie workflow and P1 guest identity reuse fix.
- No need to recreate DB pool or extend removed DTO family; auth_version hardening remains future work.

## EXECUTION

Implement this task, not a plan-only response. Read [CONTRACTS.md](CONTRACTS.md) first. Repository root is `/home/ubuntu/skn_final` in the authoring environment; resolve paths from the actual checkout. Ignore `개발 역할 분담`. This is a continuation work order; inspect and reuse existing upstream/stash implementations, then implement missing acceptance behavior. Verify dependency reports against current code before proceeding.

## READ FIRST

- `src/auth/jwt.py`
- `src/auth/deps.py`
- `src/auth/codes.py`
- `src/services/auth_service.py`
- `src/repo/user_repo.py`
- `src/routers/auth.py`
- `src/config.py`
- `frontend/js/api.js`
- `frontend/js/pages/auth.js`
- `docs/frontend_외부수정요청.md`

## EDIT SURFACE

- `src/auth/jwt.py`
- `src/auth/deps.py`
- `src/services/auth_service.py`
- `src/repo/user_repo.py`
- `src/routers/auth.py`
- `src/schemas.py`
- `src/config.py`
- `pyproject.toml, uv.lock`
- `db/migrations/<next>_auth_version.sql (if absent)`
- `tests/test_password_auth_http.py (new)`
- `frontend/js/pages/auth.js (contract mismatch only)`

Shared-file changes follow CONTRACTS dependency protocol. Do not overwrite unrelated code; preserve PC regression behavior.

## OBJECTIVE

Use merged app_user preferences and server cookies, no demo accounts. P1 guest flow must keep working. Email verification/reset mail is not silently added: frontend source lists it as separate scope; legacy request-code does not satisfy password auth.

## API CONTRACT

- POST /auth/signup: email,password,display_name,terms_agreed,privacy_agreed,marketing_agreed →201 {user}, cookie.
- POST /auth/login: email,password,remember →200 {user}, cookie.
- GET /auth/me →200 {user}, 401 if missing/invalid.
- POST /auth/logout →204, expire cookie.
- PATCH /auth/me: allowed display_name,email,marketing_agreed →200 {user}.
- POST /auth/password: current_password,new_password →204 + replacement auth cookie.
- POST /auth/withdraw: password →204 + expired cookie.
- GET /auth/email-availability?email=... →200 {available:bool}, rate limited.
- User={id,email,display_name,marketing_agreed,created_at}; never serialize password hash/lock internals or JWT.

## RULES / IMPLEMENTATION

1. Normalize email trim+lower; validation and uniqueness at API+DB. Display name1..20; password8..128 incl Latin letter+digit as current frontend contract. Check terms and privacy true; marketing optional. Argon2id hashing via maintained library and explicit pinned dependency; store salt/params in encoded hash.
2. Signup creates UUID/auth_subject=local:<uuid>, active app_user, password timestamps, consent version/timestamps and merged preferences in one transaction. No user_preference row. Handle uniqueness race→409 email_taken.
3. Login nonexistent account performs dummy Argon2 verify then401 invalid_credentials. Wrong password increments count atomically; fifth wrong resets count and locks15min; later request while locked423 account_locked. Success resets and rehashes if needed. Rate limits must work across requests and be tested (DB fields/store or shared limiter; document initial deployment constraints).
4. Validate JWT signature/expiry plus active account on every authenticated request. Existing timestamp-only iat check has same-second revocation edge: add monotonic auth_version in app_user+JWT and increment on password change/withdraw (and logout if choosing all-session invalidation). This is implementation hardening, not claim of existing source contract. Replacement cookie carries new version; old tokens invalid even within same second.
5. truefit_session HttpOnly/SameSite=Lax/Path=/; remember=true Max-Age JWT_TTL_DAYS, false session cookie with12h token. Enforce production secret config (no development default in production), secure cookie in HTTPS. Use P1 Origin/mutation policy. Do not print credentials.
6. Guest merge accepts current validated truefit_guest only; atomically transfer all its active conversations/plans to user and invalidate old guest hash/token. Preserve per-plan ownership and revisions. Never attach a browser-supplied list ID without guest proof, never move another user's list. Authenticated+guest cookie after migration must not revive guest access.
7. Profile/email changes validate and clear email_verified_at on change. Marketing toggles its timestamp in app_user. Password change verifies current hash, updates version/timestamp, issues replacement cookie.
8. Withdraw verifies password, sets deleted status/time and anonymized email/display name, erases password and preferences/marketing fields, revokes tokens; retain references needed for history. Access to deleted user's plans denied by account+owner checks. Do not cascade-delete shared catalog/review aggregates. Document retained anonymous references consistent with DB spec.
9. Logout must invalidate the emitted cookie. For server-side revocation implement documented all-session auth_version increment or a scoped session mechanism; do not claim server revocation when only clearing browser cookie. No new notification schema.

## ACCEPTANCE

- AU01 signup valid→201; duplicate case-insensitive email409; missing terms422; weak password422; DB has Argon2 hash not plaintext and preferences persisted.
- AU02 actual login→cookie→me; no cookie/JWT tampering/expired/suspended/deleted→401; cookie flags match environment.
- AU03 five wrong passwords and lock expiry with controlled clock; concurrent failures do not lose increments; unknown-email error matches wrong-password error.
- AU04 password changed within SAME second invalidates old JWT and accepts new; logout behavior matches declared scope.
- AU05 guest has two plans; signup/login transfers both, preserves data, old guest cookie loses access; foreign guest never merged.
- AU06 profile/email/marketing update persists; withdrawal anonymizes and invalidates all tokens, leaked fields absent from all responses.
- AU07 P1 anonymous use still works; actual login/signup/account page uses these APIs, no localStorage token.

## VERIFY

```bash
uv run python -m pytest -q tests/test_password_auth_http.py tests/test_baby_session_http.py
```

Run browser auth smoke or extend P5 E2E setup after dependency available. Report redacted cookie attributes, stored hash algorithm/version, merge row checks, same-second invalidation result. Do not send real emails or create external accounts.

## EXIT

All acceptance cases below must have real observed results. Write the completion report specified in CONTRACTS. Update the parent status document only for behavior actually verified. If a dependency or external gate remains unmet, report partial/blocked with its exact failing check; do not replace it with a fixed successful response.
