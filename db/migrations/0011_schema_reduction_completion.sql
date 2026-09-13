-- P0 v2 completion staging: make the v1 columns safe for post-migration writes.
-- Source table removal is deliberately not in this migration: the application
-- still has live readers which must be migrated before a later destructive DDL.
WITH chosen AS (
  SELECT DISTINCT ON (domain_id) * FROM config.domain_version
  ORDER BY domain_id, (published_at IS NOT NULL) DESC, published_at DESC NULLS LAST, version_no DESC, id
)
UPDATE config.domain d SET current_version_no=dv.version_no, definition=dv.definition,
  attribute_schema=dv.attribute_schema, content_hash=dv.content_hash
FROM chosen dv WHERE dv.domain_id=d.id AND (d.current_version_no IS NULL OR d.content_hash IS NULL);

-- New v1 JSON columns must always have their advertised top-level shape.
ALTER TABLE engine.recommendation_candidate
  ADD CONSTRAINT recommendation_candidate_evidence_refs_v1_check
  CHECK (jsonb_typeof(evidence_refs) = 'object'
    AND evidence_refs->>'schema_version' = '1'
    AND jsonb_typeof(evidence_refs->'refs') = 'array') NOT VALID;
ALTER TABLE engine.validation_result
  ADD CONSTRAINT validation_result_issues_array_check
  CHECK (jsonb_typeof(issues) = 'array') NOT VALID;
ALTER TABLE planning.requirement
  ADD CONSTRAINT requirement_slot_key_nonempty_check
  CHECK (slot_key IS NULL OR length(btrim(slot_key)) > 0) NOT VALID;
CREATE INDEX IF NOT EXISTS requirement_revision_slot_v2_idx
  ON planning.requirement(revision_id, slot_key, position);
