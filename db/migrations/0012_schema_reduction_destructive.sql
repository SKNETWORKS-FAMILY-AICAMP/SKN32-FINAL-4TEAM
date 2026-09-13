-- 0012_schema_reduction_destructive.sql
-- Fresh-database policy (P0 v3): destructive completion of the schema reduction.
-- Old-row backfill/mapping is not required (fresh_database_no_legacy_data_migration).
-- SR03 fresh-install precondition: refuse to run if a table slated for removal still
-- holds rows that were never mirrored into the forward-staged v1/v2 columns added by
-- 0010/0011. On a true fresh/disposable install this is always satisfied because the
-- application no longer writes the legacy tables once this migration lands; on an
-- existing populated legacy target that skipped 0010's backfill it fails loudly instead
-- of silently discarding data.

-- ═══════════════════════ Phase 0: fresh-install precondition guards ═══════════════════════
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM config.domain WHERE current_version_no IS NULL OR content_hash IS NULL) THEN
    RAISE EXCEPTION 'fresh_install_precondition_failed: config.domain has rows not mirrored from domain_version; run 0010 backfill first';
  END IF;
  IF EXISTS (SELECT 1 FROM identity.user_preference p LEFT JOIN identity.app_user u ON u.id=p.user_id
             WHERE u.id IS NULL) THEN
    RAISE EXCEPTION 'fresh_install_precondition_failed: identity.user_preference has rows with no matching app_user';
  END IF;
  IF EXISTS (SELECT 1 FROM catalog.product_category_membership m JOIN catalog.product p ON p.id=m.product_id
             WHERE p.category_id IS DISTINCT FROM m.category_id) THEN
    RAISE EXCEPTION 'fresh_install_precondition_failed: catalog.product.category_id does not mirror product_category_membership';
  END IF;
  IF EXISTS (SELECT 1 FROM planning.plan_node n LEFT JOIN planning.requirement r
             ON r.revision_id=n.revision_id AND r.slot_key=n.template_key AND r.position=n.position
             WHERE n.node_type='slot' AND r.id IS NULL) THEN
    RAISE EXCEPTION 'fresh_install_precondition_failed: planning.plan_node has slot rows not mirrored into requirement.slot_key/position';
  END IF;
  IF EXISTS (SELECT 1 FROM planning.owned_item o WHERE NOT EXISTS (SELECT 1 FROM planning.item i WHERE i.id=o.id)) THEN
    RAISE EXCEPTION 'fresh_install_precondition_failed: planning.owned_item has rows not copied into planning.item';
  END IF;
  IF EXISTS (SELECT 1 FROM planning.purchase_line pl WHERE NOT EXISTS (SELECT 1 FROM planning.item i WHERE i.id=pl.id)) THEN
    RAISE EXCEPTION 'fresh_install_precondition_failed: planning.purchase_line has rows not copied into planning.item';
  END IF;
  IF EXISTS (SELECT 1 FROM planning.fulfillment_allocation a JOIN planning.requirement r ON r.id=a.requirement_id
             WHERE r.fulfilled_by_item_id IS DISTINCT FROM COALESCE(a.owned_item_id, a.purchase_line_id)) THEN
    RAISE EXCEPTION 'fresh_install_precondition_failed: requirement.fulfilled_by_item_id does not mirror fulfillment_allocation';
  END IF;
  IF EXISTS (SELECT 1 FROM assets.material_revision r JOIN assets.product_material m ON m.id=r.material_id
             WHERE r.id=m.current_revision_id AND (m.file_object_id IS DISTINCT FROM r.file_object_id)) THEN
    RAISE EXCEPTION 'fresh_install_precondition_failed: assets.product_material does not mirror its current material_revision';
  END IF;
  IF EXISTS (SELECT 1 FROM evidence.source s WHERE NOT EXISTS (
             SELECT 1 FROM evidence.evidence e WHERE e.source_name=s.name AND e.source_type=s.source_type)
             AND EXISTS (SELECT 1 FROM evidence.evidence e2 WHERE e2.source_id=s.id)) THEN
    RAISE EXCEPTION 'fresh_install_precondition_failed: evidence.source referenced by evidence rows not mirrored into evidence.evidence.source_*';
  END IF;
  IF EXISTS (SELECT 1 FROM engine.candidate_evidence ce JOIN engine.recommendation_candidate c ON c.id=ce.candidate_id
             WHERE NOT (c.evidence_refs->'refs' @> jsonb_build_array(jsonb_build_object('evidence_id',ce.evidence_id::text)))) THEN
    RAISE EXCEPTION 'fresh_install_precondition_failed: candidate_evidence has rows not mirrored into recommendation_candidate.evidence_refs';
  END IF;
END $$;

-- ═══════════════════════ Phase 0b: drop notification/dataset schemas first — their tables
-- hold outward FKs into planning/community tables this migration also removes. ═══════════════════════

DROP SCHEMA notification CASCADE;
DROP SCHEMA dataset CASCADE;

-- ═══════════════════════ Phase 1: config/identity/catalog merges ═══════════════════════

-- engine.recommendation_run / evidence.review_aggregate move from domain_version_id to domain_id + snapshot.
ALTER TABLE engine.recommendation_run ADD COLUMN IF NOT EXISTS domain_id uuid;
ALTER TABLE engine.recommendation_run ADD COLUMN IF NOT EXISTS domain_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb;
UPDATE engine.recommendation_run r SET domain_id=dv.domain_id,
  domain_snapshot=jsonb_build_object('version_no',dv.version_no,'definition',dv.definition,
    'attribute_schema',dv.attribute_schema,'content_hash',dv.content_hash)
FROM config.domain_version dv WHERE dv.id=r.domain_version_id AND r.domain_id IS NULL;

ALTER TABLE evidence.review_aggregate ADD COLUMN IF NOT EXISTS domain_id uuid;
UPDATE evidence.review_aggregate a SET domain_id=dv.domain_id FROM config.domain_version dv
  WHERE dv.id=a.domain_version_id AND a.domain_id IS NULL;

ALTER TABLE engine.recommendation_run DROP CONSTRAINT IF EXISTS rec_run_domain_version_fk;
ALTER TABLE evidence.review_aggregate DROP CONSTRAINT IF EXISTS review_aggregate_domain_version_fk;
ALTER TABLE planning.plan_revision DROP CONSTRAINT IF EXISTS plan_revision_domain_version_fk;
ALTER TABLE config.domain_version DROP CONSTRAINT IF EXISTS domain_version_domain_fk;

ALTER TABLE engine.recommendation_run ALTER COLUMN domain_id SET NOT NULL;
ALTER TABLE engine.recommendation_run ADD CONSTRAINT rec_run_domain_fk FOREIGN KEY (domain_id) REFERENCES config.domain(id) ON DELETE RESTRICT;
ALTER TABLE engine.recommendation_run DROP COLUMN domain_version_id;
ALTER TABLE evidence.review_aggregate ALTER COLUMN domain_id SET NOT NULL;
ALTER TABLE evidence.review_aggregate ADD CONSTRAINT review_aggregate_domain_fk FOREIGN KEY (domain_id) REFERENCES config.domain(id) ON DELETE RESTRICT;
ALTER TABLE evidence.review_aggregate DROP COLUMN domain_version_id;
ALTER TABLE planning.plan_revision ALTER COLUMN domain_id SET NOT NULL;
ALTER TABLE planning.plan_revision DROP COLUMN domain_version_id;
ALTER TABLE config.domain ALTER COLUMN current_version_no SET NOT NULL;
ALTER TABLE config.domain ALTER COLUMN content_hash SET NOT NULL;
-- config.domain_version is dropped in Phase 6 once community.review_revision's FK to it is gone.

-- identity.user_preference already absorbed into app_user.ui_settings/preference_export (0010).
ALTER TABLE identity.user_preference DROP CONSTRAINT IF EXISTS user_preference_user_fk;
DROP TABLE identity.user_preference;

-- catalog.product_category_membership already absorbed into product.category_id (0010).
DROP TABLE catalog.product_category_membership;
ALTER TABLE catalog.product ADD CONSTRAINT product_category_fk
  FOREIGN KEY (category_id) REFERENCES catalog.product_category(id) ON DELETE RESTRICT;

-- ═══════════════════════ Phase 2: planning (plan_node / owned_item / purchase_line / fulfillment_allocation) ═══════════════════════

ALTER TABLE planning.requirement DROP CONSTRAINT IF EXISTS requirement_node_fk;
ALTER TABLE planning.requirement ALTER COLUMN slot_key SET NOT NULL;
ALTER TABLE planning.requirement DROP COLUMN node_id;
ALTER TABLE planning.plan_node DROP CONSTRAINT IF EXISTS plan_node_parent_fk;
DROP TABLE planning.plan_node;

ALTER TABLE planning.fulfillment_allocation DROP CONSTRAINT IF EXISTS alloc_requirement_fk;
ALTER TABLE planning.fulfillment_allocation DROP CONSTRAINT IF EXISTS alloc_purchase_line_fk;
ALTER TABLE planning.fulfillment_allocation DROP CONSTRAINT IF EXISTS alloc_owned_item_fk;
ALTER TABLE engine.validation_target DROP CONSTRAINT IF EXISTS validation_target_purchase_line_fk;
DROP TABLE planning.fulfillment_allocation;
DROP TABLE planning.owned_item;
DROP TABLE planning.purchase_line;

-- ═══════════════════════ Phase 3: assets (material_revision + material_applicability → product_material) ═══════════════════════

ALTER TABLE assets.product_material ADD COLUMN IF NOT EXISTS active_ingestion_id uuid;
UPDATE assets.product_material m SET active_ingestion_id=r.active_ingestion_id
  FROM assets.material_revision r WHERE r.id=m.current_revision_id AND m.active_ingestion_id IS NULL;

ALTER TABLE rag.ingestion_job DROP CONSTRAINT IF EXISTS ingestion_job_revision_fk;
ALTER TABLE assets.material_revision DROP CONSTRAINT IF EXISTS material_revision_active_ingestion_fk;
UPDATE rag.ingestion_job j SET material_id=r.material_id, material_version=r.revision_no::text
  FROM assets.material_revision r WHERE r.id=j.revision_id AND j.material_id IS NULL;
ALTER TABLE rag.ingestion_job ALTER COLUMN material_id SET NOT NULL;
ALTER TABLE rag.ingestion_job ADD CONSTRAINT ingestion_job_material_fk FOREIGN KEY (material_id) REFERENCES assets.product_material(id) ON DELETE RESTRICT;
ALTER TABLE rag.ingestion_job DROP COLUMN revision_id;

ALTER TABLE assets.product_material DROP CONSTRAINT IF EXISTS product_material_current_revision_fk;
ALTER TABLE assets.product_material ADD CONSTRAINT product_material_active_ingestion_fk
  FOREIGN KEY (active_ingestion_id) REFERENCES rag.ingestion_job(id) ON DELETE RESTRICT;
ALTER TABLE assets.product_material DROP COLUMN current_revision_id;

ALTER TABLE assets.material_applicability DROP CONSTRAINT IF EXISTS material_applicability_revision_fk;
DROP TABLE assets.material_applicability;
DROP TABLE assets.material_revision;

ALTER TABLE assets.product_material ADD CONSTRAINT product_material_file_object_fk
  FOREIGN KEY (file_object_id) REFERENCES assets.file_object(id) ON DELETE RESTRICT;

-- ═══════════════════════ Phase 4: evidence.source → evidence.evidence / offer_observation / review_summary ═══════════════════════

ALTER TABLE catalog.offer_observation ADD COLUMN IF NOT EXISTS source_name text;
ALTER TABLE catalog.offer_observation ADD COLUMN IF NOT EXISTS source_type text;
UPDATE catalog.offer_observation o SET source_name=s.name, source_type=s.source_type
  FROM evidence.source s WHERE s.id=o.source_id AND o.source_name IS NULL;
ALTER TABLE catalog.offer_observation DROP CONSTRAINT IF EXISTS offer_obs_source_fk;

ALTER TABLE evidence.review_summary ADD COLUMN IF NOT EXISTS source_name text;
ALTER TABLE evidence.review_summary ADD COLUMN IF NOT EXISTS source_type text;
UPDATE evidence.review_summary rs SET source_name=s.name, source_type=s.source_type
  FROM evidence.source s WHERE s.id=rs.source_id AND rs.source_name IS NULL;
ALTER TABLE evidence.review_summary DROP CONSTRAINT IF EXISTS review_summary_source_fk;

ALTER TABLE assets.product_material ADD COLUMN IF NOT EXISTS source_name text;
ALTER TABLE assets.product_material ADD COLUMN IF NOT EXISTS source_type text;
UPDATE assets.product_material m SET source_name=s.name, source_type=s.source_type
  FROM evidence.source s WHERE s.id=m.source_id AND m.source_name IS NULL;
ALTER TABLE assets.product_material DROP CONSTRAINT IF EXISTS product_material_source_fk;
ALTER TABLE evidence.evidence DROP CONSTRAINT IF EXISTS evidence_source_fk;

-- Backfill any not-yet-mirrored evidence.evidence.source_* before source_id is dropped.
UPDATE evidence.evidence e SET source_name=s.name, source_type=s.source_type,
  source_base_url=s.base_url, source_rating_scale=s.rating_scale
FROM evidence.source s WHERE s.id=e.source_id AND e.source_name IS NULL;

ALTER TABLE evidence.evidence ALTER COLUMN source_name SET NOT NULL;
ALTER TABLE evidence.evidence ALTER COLUMN source_type SET NOT NULL;
ALTER TABLE evidence.evidence DROP COLUMN source_id;
ALTER TABLE assets.product_material DROP COLUMN source_id;
ALTER TABLE catalog.offer_observation DROP COLUMN source_id;
ALTER TABLE evidence.review_summary DROP COLUMN source_id;

DROP TABLE evidence.source;

-- ═══════════════════════ Phase 5: engine (candidate_evidence / validation_target / validation_evidence) ═══════════════════════

-- Fold validation_target/validation_evidence into engine.validation_result.issues (typed array, v1 shape).
UPDATE engine.validation_result vr SET issues = COALESCE((
  SELECT jsonb_agg(jsonb_build_object(
    'schema_version', 1, 'rule_key', vr.rule_key, 'rule_version', vr.rule_version,
    'target', jsonb_build_object('candidate_id', t.candidate_id, 'requirement_id', t.requirement_id, 'item_id', NULL),
    'status', vr.status, 'severity', vr.severity, 'measured', vr.measured_values, 'threshold', vr.threshold,
    'reason', vr.message, 'penalty', NULL,
    'evidence_refs', COALESCE((SELECT jsonb_agg(jsonb_build_object('evidence_id', ve.evidence_id::text))
                                FROM engine.validation_evidence ve WHERE ve.validation_result_id=vr.id), '[]'::jsonb)
  )) FROM engine.validation_target t WHERE t.validation_result_id=vr.id
), '[]'::jsonb)
WHERE issues = '[]'::jsonb OR issues IS NULL;

ALTER TABLE engine.validation_target DROP CONSTRAINT IF EXISTS validation_target_result_fk;
ALTER TABLE engine.validation_target DROP CONSTRAINT IF EXISTS validation_target_requirement_fk;
ALTER TABLE engine.validation_target DROP CONSTRAINT IF EXISTS validation_target_candidate_fk;
ALTER TABLE engine.validation_evidence DROP CONSTRAINT IF EXISTS validation_evidence_result_fk;
ALTER TABLE engine.validation_evidence DROP CONSTRAINT IF EXISTS validation_evidence_evidence_fk;
DROP TABLE engine.validation_evidence;
DROP TABLE engine.validation_target;

ALTER TABLE engine.candidate_evidence DROP CONSTRAINT IF EXISTS candidate_evidence_candidate_fk;
ALTER TABLE engine.candidate_evidence DROP CONSTRAINT IF EXISTS candidate_evidence_evidence_fk;
DROP TABLE engine.candidate_evidence;

-- ═══════════════════════ Phase 6: community (pc_build/pc_build_version/review/review_revision → 2 tables) ═══════════════════════

CREATE TABLE community.review_v2 (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  record_type              text NOT NULL CHECK (record_type IN ('review','build')),
  domain                   text NOT NULL DEFAULT 'baby',
  author_user_id           uuid NOT NULL,
  subject_id               uuid,
  source_plan_revision_id  uuid,
  title                    text,
  body                     text,
  rating                   smallint CHECK (rating IS NULL OR rating BETWEEN 1 AND 5),
  axis_scores              jsonb NOT NULL DEFAULT '{}'::jsonb,
  usage_context            jsonb NOT NULL DEFAULT '{}'::jsonb,
  attributes               jsonb NOT NULL DEFAULT '{}'::jsonb,
  visibility               text NOT NULL DEFAULT 'private' CHECK (visibility IN ('private','public')),
  status                   text NOT NULL DEFAULT 'draft'
                           CHECK (status IN ('draft','published','hidden','deleted','active')),
  moderation_status        text NOT NULL DEFAULT 'pending'
                           CHECK (moderation_status IN ('pending','approved','rejected','redacted')),
  published_at             timestamptz,
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now(),
  CHECK (record_type <> 'review' OR (subject_id IS NOT NULL AND rating IS NOT NULL AND title IS NOT NULL AND body IS NOT NULL))
);

INSERT INTO community.review_v2 (id, record_type, domain, author_user_id, subject_id, title, body, rating,
    axis_scores, usage_context, status, moderation_status, published_at, created_at, updated_at)
SELECT rv.id, 'review', 'baby', r.author_user_id, r.subject_id, rv.title, rv.body, rv.rating,
    rv.axis_scores, rv.usage_context, r.status, rv.moderation_status, rv.published_at, rv.created_at, rv.updated_at
FROM community.review_revision rv JOIN community.review r ON r.id=rv.review_id AND r.current_revision_id=rv.id;

INSERT INTO community.review_v2 (id, record_type, domain, author_user_id, source_plan_revision_id,
    visibility, status, attributes, published_at, created_at, updated_at)
SELECT v.id, 'build', 'computer', b.owner_user_id, v.source_plan_revision_id,
    b.visibility, CASE WHEN v.state='published' THEN 'published' ELSE 'draft' END,
    jsonb_build_object('name', b.name, 'usage_status', v.usage_status, 'assembled_at', v.assembled_at,
      'environment', v.environment, 'configuration_hash', v.configuration_hash),
    v.published_at, v.created_at, v.updated_at
FROM community.pc_build_version v JOIN community.pc_build b ON b.id=v.build_id AND b.current_version_id=v.id;

CREATE TABLE community.review_component (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  review_id           uuid NOT NULL REFERENCES community.review_v2(id) ON DELETE RESTRICT,
  slot_key            text NOT NULL,
  position            integer NOT NULL DEFAULT 0,
  variant_id          uuid NOT NULL REFERENCES catalog.product_variant(id) ON DELETE RESTRICT,
  quantity            integer NOT NULL DEFAULT 1 CHECK (quantity > 0),
  component_snapshot  jsonb NOT NULL,
  created_at          timestamptz NOT NULL DEFAULT now()
);
INSERT INTO community.review_component (id, review_id, slot_key, position, variant_id, quantity, component_snapshot, created_at)
SELECT c.id, c.build_version_id, c.slot_key, c.position, c.variant_id, c.quantity, c.component_snapshot, c.created_at
FROM community.pc_build_component c;

-- Repoint dependents from the old identities onto community.review_v2 before dropping old tables.
ALTER TABLE evidence.review_subject DROP CONSTRAINT IF EXISTS review_subject_build_version_fk;
ALTER TABLE evidence.review_subject ADD CONSTRAINT review_subject_build_fk
  FOREIGN KEY (build_version_id) REFERENCES community.review_v2(id) ON DELETE RESTRICT;

ALTER TABLE evidence.review_summary ADD COLUMN IF NOT EXISTS review_id uuid;
UPDATE evidence.review_summary rs SET review_id=rs.review_revision_id WHERE rs.review_revision_id IS NOT NULL AND rs.review_id IS NULL;
ALTER TABLE evidence.review_summary DROP CONSTRAINT IF EXISTS review_summary_revision_fk;
ALTER TABLE evidence.review_summary ADD CONSTRAINT review_summary_review_fk
  FOREIGN KEY (review_id) REFERENCES community.review_v2(id) ON DELETE RESTRICT;
ALTER TABLE evidence.review_summary DROP COLUMN review_revision_id;

ALTER TABLE community.review DROP CONSTRAINT IF EXISTS review_current_revision_fk;
ALTER TABLE community.review_revision DROP CONSTRAINT IF EXISTS review_revision_review_fk;
ALTER TABLE community.review_revision DROP CONSTRAINT IF EXISTS review_revision_domain_version_fk;
DROP TABLE community.review_revision;
DROP TABLE community.review;
DROP TABLE config.domain_version;

ALTER TABLE community.pc_build DROP CONSTRAINT IF EXISTS pc_build_current_version_fk;
ALTER TABLE community.pc_build_version DROP CONSTRAINT IF EXISTS pc_build_version_build_fk;
ALTER TABLE community.pc_build_version DROP CONSTRAINT IF EXISTS pc_build_version_source_plan_fk;
ALTER TABLE community.pc_build_component DROP CONSTRAINT IF EXISTS pc_build_component_version_fk;
ALTER TABLE community.pc_build_component DROP CONSTRAINT IF EXISTS pc_build_component_variant_fk;
DROP TABLE community.pc_build_component;
DROP TABLE community.pc_build_version;
DROP TABLE community.pc_build;

ALTER TABLE community.review_v2 RENAME TO review;
ALTER TABLE community.review ADD CONSTRAINT review_author_fk FOREIGN KEY (author_user_id) REFERENCES identity.app_user(id) ON DELETE RESTRICT;
ALTER TABLE community.review ADD CONSTRAINT review_subject_fk FOREIGN KEY (subject_id) REFERENCES evidence.review_subject(id) ON DELETE RESTRICT;
ALTER TABLE community.review ADD CONSTRAINT review_source_plan_fk FOREIGN KEY (source_plan_revision_id) REFERENCES planning.plan_revision(id) ON DELETE RESTRICT;
CREATE INDEX review_subject_idx ON community.review (subject_id) WHERE subject_id IS NOT NULL;
CREATE INDEX review_author_idx ON community.review (author_user_id);

-- ═══════════════════════ Phase 8: unused mapping table (task item removal) ═══════════════════════

DROP TABLE IF EXISTS config.schema_reduction_mapping;

-- ═══════════════════════ Phase 9: shared schema removal (unit → catalog/planning columns already carry unit_code) ═══════════════════════

ALTER TABLE catalog.product_variant DROP CONSTRAINT IF EXISTS product_variant_unit_fk;
ALTER TABLE planning.requirement DROP CONSTRAINT IF EXISTS requirement_unit_fk;
ALTER TABLE catalog.offer_observation DROP CONSTRAINT IF EXISTS offer_obs_unit_fk;
ALTER TABLE shared.unit DROP CONSTRAINT IF EXISTS unit_base_unit_fk;

CREATE SCHEMA IF NOT EXISTS app;
CREATE OR REPLACE FUNCTION app.set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.updated_at:=now(); RETURN NEW; END $$;

DO $$
DECLARE
  t text;
  tables text[] := ARRAY[
    'config.domain','identity.app_user',
    'planning.plan','planning.plan_revision','planning.plan_condition','planning.requirement','planning.item',
    'catalog.product','catalog.product_variant','catalog.product_category','catalog.product_fact',
    'catalog.merchant','catalog.offer',
    'assets.file_object','assets.product_material',
    'rag.ingestion_job','rag.embedding_profile','rag.retrieval_run',
    'community.review',
    'evidence.evidence','evidence.review_subject','evidence.review_summary','evidence.review_aggregate',
    'engine.recommendation_run','engine.recommendation_candidate'
  ];
BEGIN
  FOREACH t IN ARRAY tables LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS set_updated_at ON %s', t);
    EXECUTE format('CREATE TRIGGER set_updated_at BEFORE UPDATE ON %s
       FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()', t);
  END LOOP;
END;
$$;

DROP SCHEMA shared CASCADE;

-- ═══════════════════════ Phase 10: final v1/v2 constraints made VALID (0011 added them NOT VALID) ═══════════════════════

ALTER TABLE engine.recommendation_candidate VALIDATE CONSTRAINT recommendation_candidate_evidence_refs_v1_check;
ALTER TABLE engine.validation_result VALIDATE CONSTRAINT validation_result_issues_array_check;
ALTER TABLE planning.requirement VALIDATE CONSTRAINT requirement_slot_key_nonempty_check;
