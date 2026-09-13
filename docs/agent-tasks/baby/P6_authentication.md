---
task_id: "P6"
status: "pending"
entry_gate: "ready_after_dependencies"
depends_on: ["P1"]
contract_version: 2
report_path: "docs/agent-tasks/baby/reports/P6.md"
---

# P6 — 가입·비밀번호 인증·설정·게스트 인계

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
