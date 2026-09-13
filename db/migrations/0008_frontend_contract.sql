-- 0008_frontend_contract.sql — 리스트 수명주기·확정 메타데이터·비동기 설명 상태

ALTER TABLE planning.plan
  ADD COLUMN status      text NOT NULL DEFAULT 'active',
  ADD COLUMN deleted_at  timestamptz,
  ADD CONSTRAINT plan_status_check
    CHECK (status IN ('active','deleted')),
  ADD CONSTRAINT plan_deleted_at_check
    CHECK ((status = 'deleted') = (deleted_at IS NOT NULL));

ALTER TABLE planning.plan_revision
  ADD COLUMN target_amount numeric(18,2),
  ADD COLUMN memo          text NOT NULL DEFAULT '',
  ADD CONSTRAINT plan_revision_target_amount_check
    CHECK (target_amount IS NULL OR target_amount >= 0),
  ADD CONSTRAINT plan_revision_memo_length_check
    CHECK (char_length(memo) <= 1000);

ALTER TABLE engine.recommendation_run
  ADD COLUMN explanation_status   text NOT NULL DEFAULT 'pending',
  ADD COLUMN explanation_headline text,
  ADD COLUMN explanation_text     text,
  ADD COLUMN reasoning_log        jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD CONSTRAINT recommendation_run_explanation_status_check
    CHECK (explanation_status IN ('pending','ready','failed')),
  ADD CONSTRAINT recommendation_run_explanation_content_check
    CHECK ((explanation_status = 'ready') = (explanation_text IS NOT NULL)),
  ADD CONSTRAINT recommendation_run_reasoning_log_check
    CHECK (jsonb_typeof(reasoning_log) = 'array');

ALTER TABLE engine.recommendation_candidate
  ADD COLUMN reason_status text NOT NULL DEFAULT 'pending',
  ADD CONSTRAINT recommendation_candidate_reason_status_check
    CHECK (reason_status IN ('pending','ready','failed')),
  ADD CONSTRAINT recommendation_candidate_reason_content_check
    CHECK ((reason_status = 'ready') = (reason IS NOT NULL));

