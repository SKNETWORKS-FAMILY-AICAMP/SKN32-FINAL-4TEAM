-- 0002_unique.sql — UNIQUE 제약·인덱스
--   · 단순/복합 UNIQUE → ALTER TABLE ADD CONSTRAINT  (FK 타깃 가능)
--   · 부분/표현식/NULLS NOT DISTINCT → CREATE UNIQUE INDEX  (PG15+ 기능, RDS PG15+ OK)
--   · (id, xxx) 복합 UNIQUE 는 6절 복합 FK(C01~C12) 타깃

-- ── config ──
ALTER TABLE config.domain            ADD CONSTRAINT domain_code_key UNIQUE (code);
ALTER TABLE config.domain_version    ADD CONSTRAINT domain_version_domain_no_key UNIQUE (domain_id, version_no);

-- ── identity ──
ALTER TABLE identity.app_user        ADD CONSTRAINT app_user_email_key UNIQUE (email_normalized);
ALTER TABLE identity.app_user        ADD CONSTRAINT app_user_auth_subject_key UNIQUE (auth_subject);
ALTER TABLE identity.message         ADD CONSTRAINT message_conv_client_key UNIQUE (conversation_id, client_message_id);

-- ── planning ──
ALTER TABLE planning.plan            ADD CONSTRAINT plan_conversation_key UNIQUE (conversation_id);
ALTER TABLE planning.plan_revision   ADD CONSTRAINT plan_revision_plan_no_key UNIQUE (plan_id, revision_no);
ALTER TABLE planning.plan_revision   ADD CONSTRAINT plan_revision_id_plan_key UNIQUE (id, plan_id);          -- C01
ALTER TABLE planning.plan_node       ADD CONSTRAINT plan_node_id_rev_key UNIQUE (id, revision_id);            -- C02/C03
ALTER TABLE planning.requirement     ADD CONSTRAINT requirement_id_rev_key UNIQUE (id, revision_id);          -- C02
ALTER TABLE planning.owned_item      ADD CONSTRAINT owned_item_id_rev_key UNIQUE (id, revision_id);           -- C02
ALTER TABLE planning.purchase_line   ADD CONSTRAINT purchase_line_id_rev_key UNIQUE (id, revision_id);        -- C02
ALTER TABLE planning.fulfillment_allocation ADD CONSTRAINT alloc_id_rev_key UNIQUE (id, revision_id);

CREATE UNIQUE INDEX plan_condition_active_key
  ON planning.plan_condition (revision_id, condition_key) WHERE status = 'active';
-- 초기 범위(§15): requirement/purchase_line/owned_item 당 연결 1개
CREATE UNIQUE INDEX alloc_requirement_key
  ON planning.fulfillment_allocation (requirement_id);
CREATE UNIQUE INDEX alloc_purchase_line_key
  ON planning.fulfillment_allocation (purchase_line_id) WHERE purchase_line_id IS NOT NULL;
CREATE UNIQUE INDEX alloc_owned_item_key
  ON planning.fulfillment_allocation (owned_item_id) WHERE owned_item_id IS NOT NULL;

-- ── catalog ──
ALTER TABLE catalog.product_variant  ADD CONSTRAINT product_variant_prod_key_key UNIQUE (product_id, variant_key);
ALTER TABLE catalog.product_variant  ADD CONSTRAINT product_variant_id_prod_key UNIQUE (id, product_id);     -- C05
ALTER TABLE catalog.product_category ADD CONSTRAINT product_category_code_key UNIQUE (code);
ALTER TABLE catalog.merchant         ADD CONSTRAINT merchant_platform_seller_key UNIQUE (platform, external_seller_id);
ALTER TABLE catalog.offer            ADD CONSTRAINT offer_merchant_ext_key UNIQUE (merchant_id, external_offer_id);
ALTER TABLE catalog.offer_observation ADD CONSTRAINT offer_obs_id_offer_key UNIQUE (id, offer_id);           -- C04

CREATE UNIQUE INDEX product_variant_gtin_key
  ON catalog.product_variant (gtin) WHERE gtin IS NOT NULL;

-- ── assets ──
ALTER TABLE assets.file_object       ADD CONSTRAINT file_object_bucket_key_ver_key UNIQUE (bucket, object_key, storage_version);
ALTER TABLE assets.material_revision ADD CONSTRAINT material_revision_mat_no_key UNIQUE (material_id, revision_no);
ALTER TABLE assets.material_revision ADD CONSTRAINT material_revision_id_mat_key UNIQUE (id, material_id);    -- C06

CREATE UNIQUE INDEX material_applicability_scope_key
  ON assets.material_applicability (revision_id, product_id, variant_id) NULLS NOT DISTINCT;

-- ── rag ──
ALTER TABLE rag.ingestion_job        ADD CONSTRAINT ingestion_job_idem_key UNIQUE (idempotency_key);
ALTER TABLE rag.ingestion_job        ADD CONSTRAINT ingestion_job_id_rev_key UNIQUE (id, revision_id);       -- C06
ALTER TABLE rag.document_chunk       ADD CONSTRAINT document_chunk_ing_ord_key UNIQUE (ingestion_id, ordinal);
ALTER TABLE rag.embedding_profile    ADD CONSTRAINT embedding_profile_key_key UNIQUE (profile_key);
ALTER TABLE rag.retrieval_run        ADD CONSTRAINT retrieval_run_id_profile_key UNIQUE (id, profile_id);    -- C08
ALTER TABLE rag.retrieval_hit        ADD CONSTRAINT retrieval_hit_run_rank_key UNIQUE (retrieval_run_id, rank_no);
ALTER TABLE rag.retrieval_hit        ADD CONSTRAINT retrieval_hit_run_chunk_key UNIQUE (retrieval_run_id, chunk_id);

-- ── community ──
ALTER TABLE community.pc_build_version ADD CONSTRAINT pc_build_version_build_no_key UNIQUE (build_id, version_no);
ALTER TABLE community.pc_build_version ADD CONSTRAINT pc_build_version_id_build_key UNIQUE (id, build_id);    -- C10
ALTER TABLE community.pc_build_component ADD CONSTRAINT pc_build_component_slot_pos_key UNIQUE (build_version_id, slot_key, position);
ALTER TABLE community.review          ADD CONSTRAINT review_author_subject_key UNIQUE (author_user_id, subject_id);
ALTER TABLE community.review_revision ADD CONSTRAINT review_revision_review_no_key UNIQUE (review_id, revision_no);
ALTER TABLE community.review_revision ADD CONSTRAINT review_revision_id_review_key UNIQUE (id, review_id);    -- C12

-- ── evidence ──
CREATE UNIQUE INDEX review_subject_product_key    ON evidence.review_subject (product_id)       WHERE product_id IS NOT NULL;
CREATE UNIQUE INDEX review_subject_variant_key    ON evidence.review_subject (variant_id)       WHERE variant_id IS NOT NULL;
CREATE UNIQUE INDEX review_subject_offer_key      ON evidence.review_subject (offer_id)         WHERE offer_id IS NOT NULL;
CREATE UNIQUE INDEX review_subject_build_ver_key  ON evidence.review_subject (build_version_id) WHERE build_version_id IS NOT NULL;

CREATE UNIQUE INDEX review_summary_external_key
  ON evidence.review_summary (source_id, external_review_key, processing_version)
  WHERE external_review_key IS NOT NULL;
CREATE UNIQUE INDEX review_summary_internal_key
  ON evidence.review_summary (review_revision_id, processing_version)
  WHERE review_revision_id IS NOT NULL;

-- ── engine ──
ALTER TABLE engine.feedback_event    ADD CONSTRAINT feedback_event_key_key UNIQUE (event_key);

CREATE UNIQUE INDEX validation_target_req_key
  ON engine.validation_target (validation_result_id, requirement_id)   WHERE requirement_id IS NOT NULL;
CREATE UNIQUE INDEX validation_target_line_key
  ON engine.validation_target (validation_result_id, purchase_line_id) WHERE purchase_line_id IS NOT NULL;
CREATE UNIQUE INDEX validation_target_cand_key
  ON engine.validation_target (validation_result_id, candidate_id)     WHERE candidate_id IS NOT NULL;

-- ── notification ──
ALTER TABLE notification.notification_event ADD CONSTRAINT notification_event_dedupe_key UNIQUE (dedupe_key);

CREATE UNIQUE INDEX price_watch_active_scope_key
  ON notification.price_watch (revision_id, purchase_line_id) NULLS NOT DISTINCT
  WHERE state = 'active';

-- ── dataset ──
ALTER TABLE dataset.generation_run   ADD CONSTRAINT generation_run_idem_key UNIQUE (idempotency_key);
ALTER TABLE dataset.label_definition ADD CONSTRAINT label_definition_task_no_key UNIQUE (task_code, version_no);
ALTER TABLE dataset.review_label     ADD CONSTRAINT review_label_sample_def_no_key UNIQUE (sample_id, label_definition_id, revision_no);

CREATE UNIQUE INDEX review_sample_source_summary_key
  ON dataset.review_sample (source_summary_id)        WHERE source_summary_id IS NOT NULL;
CREATE UNIQUE INDEX review_sample_source_revision_key
  ON dataset.review_sample (source_review_revision_id) WHERE source_review_revision_id IS NOT NULL;
CREATE UNIQUE INDEX review_sample_generation_key
  ON dataset.review_sample (generation_run_id, generation_item_key) WHERE generation_run_id IS NOT NULL;
CREATE UNIQUE INDEX review_sample_external_ref_key
  ON dataset.review_sample (
    (external_dataset_ref->>'dataset_name'),
    (external_dataset_ref->>'version'),
    (external_dataset_ref->>'record_id')
  ) WHERE external_dataset_ref IS NOT NULL;
CREATE UNIQUE INDEX review_label_approved_key
  ON dataset.review_label (sample_id, label_definition_id) WHERE review_status = 'approved';
