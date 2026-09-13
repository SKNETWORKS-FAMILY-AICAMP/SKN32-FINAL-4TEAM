-- P0 reduced schema v1. Forward-only: rag/pgvector remains retained.
-- Legacy source tables are intentionally retained through this release; dropping
-- them is forbidden until mapping reports prove no ambiguous source row exists.
CREATE TABLE IF NOT EXISTS config.schema_reduction_mapping (
  mapping_type text NOT NULL, source_id uuid NOT NULL, target_id uuid NOT NULL,
  reviewed_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (mapping_type, source_id)
);
ALTER TABLE config.domain_version ADD COLUMN IF NOT EXISTS published_at timestamptz;
ALTER TABLE config.domain ADD COLUMN IF NOT EXISTS current_version_no integer;
ALTER TABLE config.domain ADD COLUMN IF NOT EXISTS definition jsonb;
ALTER TABLE config.domain ADD COLUMN IF NOT EXISTS attribute_schema jsonb;
ALTER TABLE config.domain ADD COLUMN IF NOT EXISTS content_hash text;
ALTER TABLE identity.app_user ADD COLUMN IF NOT EXISTS ui_settings jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE identity.app_user ADD COLUMN IF NOT EXISTS preference_export jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE catalog.product ADD COLUMN IF NOT EXISTS category_id uuid;
ALTER TABLE planning.plan_revision ADD COLUMN IF NOT EXISTS domain_id uuid;
ALTER TABLE planning.plan_revision ADD COLUMN IF NOT EXISTS domain_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE planning.requirement ADD COLUMN IF NOT EXISTS slot_key text;
ALTER TABLE planning.requirement ADD COLUMN IF NOT EXISTS group_key text;
ALTER TABLE planning.requirement ADD COLUMN IF NOT EXISTS position integer NOT NULL DEFAULT 0;
ALTER TABLE planning.requirement ADD COLUMN IF NOT EXISTS fulfilled_by_item_id uuid;
CREATE TABLE IF NOT EXISTS planning.item (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), revision_id uuid NOT NULL, variant_id uuid,
 offer_id uuid, offer_observation_id uuid, status text NOT NULL CHECK(status IN ('owned','to_purchase','purchased')),
 qty numeric(18,4) NOT NULL CHECK(qty>0), unit_code text NOT NULL DEFAULT 'each',
 unit_qty numeric(18,4) NOT NULL DEFAULT 1 CHECK(unit_qty>0), timing text NOT NULL DEFAULT 'now' CHECK(timing IN ('now','soon','later')),
 selected boolean NOT NULL DEFAULT false, price_observation jsonb NOT NULL DEFAULT '{}'::jsonb,
 item_spec jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
ALTER TABLE assets.product_material ADD COLUMN IF NOT EXISTS file_object_id uuid;
ALTER TABLE assets.product_material ADD COLUMN IF NOT EXISTS version text;
ALTER TABLE assets.product_material ADD COLUMN IF NOT EXISTS source_url text;
ALTER TABLE assets.product_material ADD COLUMN IF NOT EXISTS language text;
ALTER TABLE assets.product_material ADD COLUMN IF NOT EXISTS retrieved_at timestamptz;
ALTER TABLE assets.product_material ADD COLUMN IF NOT EXISTS material_status text;
ALTER TABLE assets.product_material ADD COLUMN IF NOT EXISTS applicability jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE rag.ingestion_job ADD COLUMN IF NOT EXISTS material_id uuid;
ALTER TABLE rag.ingestion_job ADD COLUMN IF NOT EXISTS material_version text;
ALTER TABLE evidence.evidence ADD COLUMN IF NOT EXISTS source_name text;
ALTER TABLE evidence.evidence ADD COLUMN IF NOT EXISTS source_type text;
ALTER TABLE evidence.evidence ADD COLUMN IF NOT EXISTS source_base_url text;
ALTER TABLE evidence.evidence ADD COLUMN IF NOT EXISTS source_rating_scale jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE engine.recommendation_candidate ADD COLUMN IF NOT EXISTS evidence_refs jsonb NOT NULL DEFAULT '{"schema_version":1,"refs":[]}'::jsonb;
ALTER TABLE engine.validation_result ADD COLUMN IF NOT EXISTS issues jsonb NOT NULL DEFAULT '[]'::jsonb;
WITH ranked AS (SELECT dv.*,row_number() OVER(PARTITION BY domain_id ORDER BY (published_at IS NOT NULL) DESC,published_at DESC NULLS LAST,version_no DESC,id) n FROM config.domain_version dv)
UPDATE config.domain d SET current_version_no=r.version_no,definition=r.definition,attribute_schema=r.attribute_schema,content_hash=r.content_hash FROM ranked r WHERE r.domain_id=d.id AND r.n=1;
UPDATE planning.plan_revision r SET domain_id=dv.domain_id,domain_snapshot=jsonb_build_object('version_no',dv.version_no,'definition',dv.definition,'attribute_schema',dv.attribute_schema,'content_hash',dv.content_hash) FROM config.domain_version dv WHERE dv.id=r.domain_version_id;
UPDATE identity.app_user u SET ui_settings=COALESCE(p.ui_settings,'{}'::jsonb),preference_export=jsonb_build_object('notification_settings',p.notification_settings) FROM identity.user_preference p WHERE p.user_id=u.id;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM catalog.product_category_membership GROUP BY product_id HAVING count(*)>1) THEN RAISE EXCEPTION 'schema_reduction_conflict: multiple categories require config.schema_reduction_mapping'; END IF; END $$;
UPDATE catalog.product p SET category_id=m.category_id FROM catalog.product_category_membership m WHERE m.product_id=p.id;
UPDATE planning.requirement r SET slot_key=n.template_key,position=n.position FROM planning.plan_node n WHERE n.id=r.node_id;
INSERT INTO planning.item(id,revision_id,variant_id,status,qty,unit_code,item_spec) SELECT id,revision_id,variant_id,'owned',quantity,unit_code,item_spec FROM planning.owned_item ON CONFLICT(id) DO NOTHING;
INSERT INTO planning.item(id,revision_id,offer_id,offer_observation_id,status,qty,unit_code,selected,price_observation,item_spec) SELECT id,revision_id,offer_id,selected_observation_id,'to_purchase',pack_count,'each',true,jsonb_build_object('line_amount',line_amount,'currency',currency),snapshot FROM planning.purchase_line ON CONFLICT(id) DO NOTHING;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM planning.fulfillment_allocation GROUP BY requirement_id HAVING count(*)>1) THEN RAISE EXCEPTION 'schema_reduction_conflict: multi-item allocation requires reviewed split mapping'; END IF; END $$;
UPDATE planning.requirement r SET fulfilled_by_item_id=COALESCE(a.owned_item_id,a.purchase_line_id) FROM planning.fulfillment_allocation a WHERE a.requirement_id=r.id;
UPDATE assets.product_material m SET file_object_id=r.file_object_id,version=r.revision_no::text,source_url=r.source_url,language=r.language,retrieved_at=r.retrieved_at,material_status=r.status,applicability=COALESCE((SELECT jsonb_agg(jsonb_build_object('product_id',a.product_id,'variant_id',a.variant_id,'conditions',a.conditions,'verified',a.verified)) FROM assets.material_applicability a WHERE a.revision_id=r.id),'[]'::jsonb) FROM assets.material_revision r WHERE r.id=m.current_revision_id;
UPDATE rag.ingestion_job j SET material_id=r.material_id,material_version=r.revision_no::text FROM assets.material_revision r WHERE r.id=j.revision_id;
UPDATE evidence.evidence e SET source_name=s.name,source_type=s.source_type,source_base_url=s.base_url,source_rating_scale=s.rating_scale FROM evidence.source s WHERE s.id=e.source_id;
UPDATE engine.recommendation_candidate c SET evidence_refs=jsonb_build_object('schema_version',1,'refs',COALESCE((SELECT jsonb_agg(jsonb_build_object('evidence_id',ce.evidence_id,'claim_key',ce.claim_key)) FROM engine.candidate_evidence ce WHERE ce.candidate_id=c.id),'[]'::jsonb));
CREATE SCHEMA IF NOT EXISTS app;
CREATE OR REPLACE FUNCTION app.set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.updated_at:=now(); RETURN NEW; END $$;
DROP TRIGGER IF EXISTS set_updated_at ON planning.item;
CREATE TRIGGER set_updated_at BEFORE UPDATE ON planning.item FOR EACH ROW EXECUTE FUNCTION app.set_updated_at();
CREATE INDEX IF NOT EXISTS planning_item_revision_idx ON planning.item(revision_id);
CREATE INDEX IF NOT EXISTS requirement_slot_idx ON planning.requirement(revision_id,slot_key,position);
