-- 0009_frontend_requirement_revision.sql — 3차 프론트 요구 보정
-- 0007/0008 적용 이후에도 안전하도록 새 컬럼과 트리거를 forward-only로 추가한다.

ALTER TABLE identity.app_user
  ADD COLUMN email_verified_at timestamptz,
  ADD COLUMN updated_at        timestamptz NOT NULL DEFAULT now();

ALTER TABLE identity.user_preference
  ADD COLUMN ui_settings jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE TRIGGER set_updated_at
BEFORE UPDATE ON identity.app_user
FOR EACH ROW EXECUTE FUNCTION shared.set_updated_at();

