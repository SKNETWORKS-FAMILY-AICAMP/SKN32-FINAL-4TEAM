-- 0015_auth_version.sql — 비밀번호 인증 하드닝: 단조 증가 auth_version.
--
-- 기존 JWT 검증은 서명/만료만 확인해 같은 초(iat 해상도)에 비밀번호를 바꿔도 이전
-- 토큰이 그대로 유효한 재발급-경쟁 허점이 있었다(P6 RULES #4). app_user 에 발급 세대를
-- 두고 JWT 클레임에 같은 값을 실어, 비밀번호 변경/탈퇴 시 이 값을 올리면 그 순간
-- 이전에 발급된 토큰은 세대 불일치로 즉시 무효가 된다.

ALTER TABLE identity.app_user
  ADD COLUMN auth_version integer NOT NULL DEFAULT 0;

ALTER TABLE identity.app_user
  ADD CONSTRAINT app_user_auth_version_check CHECK (auth_version >= 0);
