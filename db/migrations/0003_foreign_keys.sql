-- 0003_foreign_keys.sql — 모든 FK (ALTER TABLE ADD CONSTRAINT)
--   · 삭제 정책: ON DELETE RESTRICT (명세서 §2.2). 운영상 숨김·철회·탈퇴를 먼저 처리.
--   · nullable 복합 FK 는 MATCH SIMPLE(기본) — 컬럼 하나라도 NULL 이면 통과 (§C02)
--   · C01~C12: (자식.포인터, 자식.식별) → (부모.id, 부모.소속) 복합 FK 로 같은 소속 강제

-- ── config ──
ALTER TABLE config.domain_version
  ADD CONSTRAINT domain_version_domain_fk FOREIGN KEY (domain_id)
  REFERENCES config.domain (id) ON DELETE RESTRICT;

-- ── identity ──
ALTER TABLE identity.user_preference
  ADD CONSTRAINT user_preference_user_fk FOREIGN KEY (user_id)
  REFERENCES identity.app_user (id) ON DELETE RESTRICT;
ALTER TABLE identity.conversation
  ADD CONSTRAINT conversation_user_fk FOREIGN KEY (user_id)
  REFERENCES identity.app_user (id) ON DELETE RESTRICT;
ALTER TABLE identity.message
  ADD CONSTRAINT message_conversation_fk FOREIGN KEY (conversation_id)
  REFERENCES identity.conversation (id) ON DELETE RESTRICT;

-- ── shared ──
ALTER TABLE shared.unit
  ADD CONSTRAINT unit_base_unit_fk FOREIGN KEY (base_unit_code)
  REFERENCES shared.unit (code) ON DELETE RESTRICT;

-- ── planning ──
ALTER TABLE planning.plan
  ADD CONSTRAINT plan_conversation_fk FOREIGN KEY (conversation_id)
  REFERENCES identity.conversation (id) ON DELETE RESTRICT;
ALTER TABLE planning.plan
  ADD CONSTRAINT plan_owner_fk FOREIGN KEY (owner_user_id)
  REFERENCES identity.app_user (id) ON DELETE RESTRICT;
ALTER TABLE planning.plan
  ADD CONSTRAINT plan_current_revision_fk FOREIGN KEY (current_revision_id, id)   -- C01
  REFERENCES planning.plan_revision (id, plan_id) ON DELETE RESTRICT;

ALTER TABLE planning.plan_revision
  ADD CONSTRAINT plan_revision_plan_fk FOREIGN KEY (plan_id)
  REFERENCES planning.plan (id) ON DELETE RESTRICT;
ALTER TABLE planning.plan_revision
  ADD CONSTRAINT plan_revision_domain_version_fk FOREIGN KEY (domain_version_id)
  REFERENCES config.domain_version (id) ON DELETE RESTRICT;

ALTER TABLE planning.plan_condition
  ADD CONSTRAINT plan_condition_revision_fk FOREIGN KEY (revision_id)
  REFERENCES planning.plan_revision (id) ON DELETE RESTRICT;
ALTER TABLE planning.plan_condition
  ADD CONSTRAINT plan_condition_message_fk FOREIGN KEY (source_message_id)
  REFERENCES identity.message (id) ON DELETE RESTRICT;
ALTER TABLE planning.plan_condition
  ADD CONSTRAINT plan_condition_supersedes_fk FOREIGN KEY (supersedes_id)
  REFERENCES planning.plan_condition (id) ON DELETE RESTRICT;

ALTER TABLE planning.plan_node
  ADD CONSTRAINT plan_node_revision_fk FOREIGN KEY (revision_id)
  REFERENCES planning.plan_revision (id) ON DELETE RESTRICT;
ALTER TABLE planning.plan_node
  ADD CONSTRAINT plan_node_parent_fk FOREIGN KEY (parent_id, revision_id)         -- C03
  REFERENCES planning.plan_node (id, revision_id) ON DELETE RESTRICT;

ALTER TABLE planning.requirement
  ADD CONSTRAINT requirement_revision_fk FOREIGN KEY (revision_id)
  REFERENCES planning.plan_revision (id) ON DELETE RESTRICT;
ALTER TABLE planning.requirement
  ADD CONSTRAINT requirement_node_fk FOREIGN KEY (node_id, revision_id)           -- C02
  REFERENCES planning.plan_node (id, revision_id) ON DELETE RESTRICT;
ALTER TABLE planning.requirement
  ADD CONSTRAINT requirement_unit_fk FOREIGN KEY (unit_code)
  REFERENCES shared.unit (code) ON DELETE RESTRICT;

ALTER TABLE planning.owned_item
  ADD CONSTRAINT owned_item_revision_fk FOREIGN KEY (revision_id)
  REFERENCES planning.plan_revision (id) ON DELETE RESTRICT;
ALTER TABLE planning.owned_item
  ADD CONSTRAINT owned_item_variant_fk FOREIGN KEY (variant_id)
  REFERENCES catalog.product_variant (id) ON DELETE RESTRICT;
ALTER TABLE planning.owned_item
  ADD CONSTRAINT owned_item_unit_fk FOREIGN KEY (unit_code)
  REFERENCES shared.unit (code) ON DELETE RESTRICT;
ALTER TABLE planning.owned_item
  ADD CONSTRAINT owned_item_source_condition_fk FOREIGN KEY (source_condition_id)
  REFERENCES planning.plan_condition (id) ON DELETE RESTRICT;

ALTER TABLE planning.purchase_line
  ADD CONSTRAINT purchase_line_revision_fk FOREIGN KEY (revision_id)
  REFERENCES planning.plan_revision (id) ON DELETE RESTRICT;
ALTER TABLE planning.purchase_line
  ADD CONSTRAINT purchase_line_offer_fk FOREIGN KEY (offer_id)
  REFERENCES catalog.offer (id) ON DELETE RESTRICT;
ALTER TABLE planning.purchase_line
  ADD CONSTRAINT purchase_line_observation_fk FOREIGN KEY (selected_observation_id, offer_id)  -- C04
  REFERENCES catalog.offer_observation (id, offer_id) ON DELETE RESTRICT;

ALTER TABLE planning.fulfillment_allocation
  ADD CONSTRAINT alloc_revision_fk FOREIGN KEY (revision_id)
  REFERENCES planning.plan_revision (id) ON DELETE RESTRICT;
ALTER TABLE planning.fulfillment_allocation
  ADD CONSTRAINT alloc_requirement_fk FOREIGN KEY (requirement_id, revision_id)   -- C02
  REFERENCES planning.requirement (id, revision_id) ON DELETE RESTRICT;
ALTER TABLE planning.fulfillment_allocation
  ADD CONSTRAINT alloc_purchase_line_fk FOREIGN KEY (purchase_line_id, revision_id)  -- C02
  REFERENCES planning.purchase_line (id, revision_id) ON DELETE RESTRICT;
ALTER TABLE planning.fulfillment_allocation
  ADD CONSTRAINT alloc_owned_item_fk FOREIGN KEY (owned_item_id, revision_id)     -- C02
  REFERENCES planning.owned_item (id, revision_id) ON DELETE RESTRICT;
ALTER TABLE planning.fulfillment_allocation
  ADD CONSTRAINT alloc_unit_fk FOREIGN KEY (unit_code)
  REFERENCES shared.unit (code) ON DELETE RESTRICT;

-- ── catalog ──
ALTER TABLE catalog.product_variant
  ADD CONSTRAINT product_variant_product_fk FOREIGN KEY (product_id)
  REFERENCES catalog.product (id) ON DELETE RESTRICT;
ALTER TABLE catalog.product_variant
  ADD CONSTRAINT product_variant_unit_fk FOREIGN KEY (unit_code)
  REFERENCES shared.unit (code) ON DELETE RESTRICT;

ALTER TABLE catalog.product_category
  ADD CONSTRAINT product_category_parent_fk FOREIGN KEY (parent_id)
  REFERENCES catalog.product_category (id) ON DELETE RESTRICT;

ALTER TABLE catalog.product_category_membership
  ADD CONSTRAINT pcm_product_fk FOREIGN KEY (product_id)
  REFERENCES catalog.product (id) ON DELETE RESTRICT;
ALTER TABLE catalog.product_category_membership
  ADD CONSTRAINT pcm_category_fk FOREIGN KEY (category_id)
  REFERENCES catalog.product_category (id) ON DELETE RESTRICT;

ALTER TABLE catalog.product_fact
  ADD CONSTRAINT product_fact_product_fk FOREIGN KEY (product_id)
  REFERENCES catalog.product (id) ON DELETE RESTRICT;
ALTER TABLE catalog.product_fact
  ADD CONSTRAINT product_fact_variant_fk FOREIGN KEY (variant_id, product_id)     -- C05
  REFERENCES catalog.product_variant (id, product_id) ON DELETE RESTRICT;
ALTER TABLE catalog.product_fact
  ADD CONSTRAINT product_fact_unit_fk FOREIGN KEY (unit_code)
  REFERENCES shared.unit (code) ON DELETE RESTRICT;
ALTER TABLE catalog.product_fact
  ADD CONSTRAINT product_fact_evidence_fk FOREIGN KEY (evidence_id)
  REFERENCES evidence.evidence (id) ON DELETE RESTRICT;

ALTER TABLE catalog.offer
  ADD CONSTRAINT offer_variant_fk FOREIGN KEY (variant_id)
  REFERENCES catalog.product_variant (id) ON DELETE RESTRICT;
ALTER TABLE catalog.offer
  ADD CONSTRAINT offer_merchant_fk FOREIGN KEY (merchant_id)
  REFERENCES catalog.merchant (id) ON DELETE RESTRICT;

ALTER TABLE catalog.offer_observation
  ADD CONSTRAINT offer_obs_offer_fk FOREIGN KEY (offer_id)
  REFERENCES catalog.offer (id) ON DELETE RESTRICT;
ALTER TABLE catalog.offer_observation
  ADD CONSTRAINT offer_obs_source_fk FOREIGN KEY (source_id)
  REFERENCES evidence.source (id) ON DELETE RESTRICT;

-- ── assets ──
ALTER TABLE assets.file_object
  ADD CONSTRAINT file_object_uploaded_by_fk FOREIGN KEY (uploaded_by)
  REFERENCES identity.app_user (id) ON DELETE RESTRICT;

ALTER TABLE assets.product_material
  ADD CONSTRAINT product_material_source_fk FOREIGN KEY (source_id)
  REFERENCES evidence.source (id) ON DELETE RESTRICT;
ALTER TABLE assets.product_material
  ADD CONSTRAINT product_material_current_revision_fk FOREIGN KEY (current_revision_id, id)  -- C06
  REFERENCES assets.material_revision (id, material_id) ON DELETE RESTRICT;

ALTER TABLE assets.material_revision
  ADD CONSTRAINT material_revision_material_fk FOREIGN KEY (material_id)
  REFERENCES assets.product_material (id) ON DELETE RESTRICT;
ALTER TABLE assets.material_revision
  ADD CONSTRAINT material_revision_file_fk FOREIGN KEY (file_object_id)
  REFERENCES assets.file_object (id) ON DELETE RESTRICT;
ALTER TABLE assets.material_revision
  ADD CONSTRAINT material_revision_active_ingestion_fk FOREIGN KEY (active_ingestion_id, id)  -- C06
  REFERENCES rag.ingestion_job (id, revision_id) ON DELETE RESTRICT;

ALTER TABLE assets.material_applicability
  ADD CONSTRAINT material_applicability_revision_fk FOREIGN KEY (revision_id)
  REFERENCES assets.material_revision (id) ON DELETE RESTRICT;
ALTER TABLE assets.material_applicability
  ADD CONSTRAINT material_applicability_product_fk FOREIGN KEY (product_id)
  REFERENCES catalog.product (id) ON DELETE RESTRICT;
ALTER TABLE assets.material_applicability
  ADD CONSTRAINT material_applicability_variant_fk FOREIGN KEY (variant_id, product_id)  -- C05
  REFERENCES catalog.product_variant (id, product_id) ON DELETE RESTRICT;

-- ── rag ──
ALTER TABLE rag.ingestion_job
  ADD CONSTRAINT ingestion_job_revision_fk FOREIGN KEY (revision_id)
  REFERENCES assets.material_revision (id) ON DELETE RESTRICT;

ALTER TABLE rag.document_chunk
  ADD CONSTRAINT document_chunk_ingestion_fk FOREIGN KEY (ingestion_id)
  REFERENCES rag.ingestion_job (id) ON DELETE RESTRICT;

ALTER TABLE rag.chunk_embedding
  ADD CONSTRAINT chunk_embedding_chunk_fk FOREIGN KEY (chunk_id)
  REFERENCES rag.document_chunk (id) ON DELETE RESTRICT;
ALTER TABLE rag.chunk_embedding
  ADD CONSTRAINT chunk_embedding_profile_fk FOREIGN KEY (profile_id)
  REFERENCES rag.embedding_profile (id) ON DELETE RESTRICT;

ALTER TABLE rag.retrieval_run
  ADD CONSTRAINT retrieval_run_rec_run_fk FOREIGN KEY (recommendation_run_id)
  REFERENCES engine.recommendation_run (id) ON DELETE RESTRICT;
ALTER TABLE rag.retrieval_run
  ADD CONSTRAINT retrieval_run_profile_fk FOREIGN KEY (profile_id)
  REFERENCES rag.embedding_profile (id) ON DELETE RESTRICT;

ALTER TABLE rag.retrieval_hit
  ADD CONSTRAINT retrieval_hit_run_fk FOREIGN KEY (retrieval_run_id, profile_id)  -- C08
  REFERENCES rag.retrieval_run (id, profile_id) ON DELETE RESTRICT;
ALTER TABLE rag.retrieval_hit
  ADD CONSTRAINT retrieval_hit_embedding_fk FOREIGN KEY (chunk_id, profile_id)    -- C08
  REFERENCES rag.chunk_embedding (chunk_id, profile_id) ON DELETE RESTRICT;
ALTER TABLE rag.retrieval_hit
  ADD CONSTRAINT retrieval_hit_chunk_fk FOREIGN KEY (chunk_id)
  REFERENCES rag.document_chunk (id) ON DELETE RESTRICT;
ALTER TABLE rag.retrieval_hit
  ADD CONSTRAINT retrieval_hit_profile_fk FOREIGN KEY (profile_id)
  REFERENCES rag.embedding_profile (id) ON DELETE RESTRICT;

-- ── community ──
ALTER TABLE community.pc_build
  ADD CONSTRAINT pc_build_owner_fk FOREIGN KEY (owner_user_id)
  REFERENCES identity.app_user (id) ON DELETE RESTRICT;
ALTER TABLE community.pc_build
  ADD CONSTRAINT pc_build_current_version_fk FOREIGN KEY (current_version_id, id)  -- C10
  REFERENCES community.pc_build_version (id, build_id) ON DELETE RESTRICT;

ALTER TABLE community.pc_build_version
  ADD CONSTRAINT pc_build_version_build_fk FOREIGN KEY (build_id)
  REFERENCES community.pc_build (id) ON DELETE RESTRICT;
ALTER TABLE community.pc_build_version
  ADD CONSTRAINT pc_build_version_source_plan_fk FOREIGN KEY (source_plan_revision_id)
  REFERENCES planning.plan_revision (id) ON DELETE RESTRICT;

ALTER TABLE community.pc_build_component
  ADD CONSTRAINT pc_build_component_version_fk FOREIGN KEY (build_version_id)
  REFERENCES community.pc_build_version (id) ON DELETE RESTRICT;
ALTER TABLE community.pc_build_component
  ADD CONSTRAINT pc_build_component_variant_fk FOREIGN KEY (variant_id)
  REFERENCES catalog.product_variant (id) ON DELETE RESTRICT;

ALTER TABLE community.review
  ADD CONSTRAINT review_author_fk FOREIGN KEY (author_user_id)
  REFERENCES identity.app_user (id) ON DELETE RESTRICT;
ALTER TABLE community.review
  ADD CONSTRAINT review_subject_fk FOREIGN KEY (subject_id)
  REFERENCES evidence.review_subject (id) ON DELETE RESTRICT;
ALTER TABLE community.review
  ADD CONSTRAINT review_current_revision_fk FOREIGN KEY (current_revision_id, id)  -- C12
  REFERENCES community.review_revision (id, review_id) ON DELETE RESTRICT;

ALTER TABLE community.review_revision
  ADD CONSTRAINT review_revision_review_fk FOREIGN KEY (review_id)
  REFERENCES community.review (id) ON DELETE RESTRICT;
ALTER TABLE community.review_revision
  ADD CONSTRAINT review_revision_domain_version_fk FOREIGN KEY (domain_version_id)
  REFERENCES config.domain_version (id) ON DELETE RESTRICT;

-- ── evidence ──
ALTER TABLE evidence.evidence
  ADD CONSTRAINT evidence_source_fk FOREIGN KEY (source_id)
  REFERENCES evidence.source (id) ON DELETE RESTRICT;
ALTER TABLE evidence.evidence
  ADD CONSTRAINT evidence_retrieval_hit_fk FOREIGN KEY (retrieval_hit_id)
  REFERENCES rag.retrieval_hit (id) ON DELETE RESTRICT;
ALTER TABLE evidence.evidence
  ADD CONSTRAINT evidence_review_aggregate_fk FOREIGN KEY (review_aggregate_id)
  REFERENCES evidence.review_aggregate (id) ON DELETE RESTRICT;

ALTER TABLE evidence.review_subject
  ADD CONSTRAINT review_subject_product_fk FOREIGN KEY (product_id)
  REFERENCES catalog.product (id) ON DELETE RESTRICT;
ALTER TABLE evidence.review_subject
  ADD CONSTRAINT review_subject_variant_fk FOREIGN KEY (variant_id)
  REFERENCES catalog.product_variant (id) ON DELETE RESTRICT;
ALTER TABLE evidence.review_subject
  ADD CONSTRAINT review_subject_offer_fk FOREIGN KEY (offer_id)
  REFERENCES catalog.offer (id) ON DELETE RESTRICT;
ALTER TABLE evidence.review_subject
  ADD CONSTRAINT review_subject_build_version_fk FOREIGN KEY (build_version_id)
  REFERENCES community.pc_build_version (id) ON DELETE RESTRICT;

ALTER TABLE evidence.review_summary
  ADD CONSTRAINT review_summary_subject_fk FOREIGN KEY (subject_id)
  REFERENCES evidence.review_subject (id) ON DELETE RESTRICT;
ALTER TABLE evidence.review_summary
  ADD CONSTRAINT review_summary_source_fk FOREIGN KEY (source_id)
  REFERENCES evidence.source (id) ON DELETE RESTRICT;
ALTER TABLE evidence.review_summary
  ADD CONSTRAINT review_summary_revision_fk FOREIGN KEY (review_revision_id)
  REFERENCES community.review_revision (id) ON DELETE RESTRICT;

ALTER TABLE evidence.review_aggregate
  ADD CONSTRAINT review_aggregate_subject_fk FOREIGN KEY (subject_id)
  REFERENCES evidence.review_subject (id) ON DELETE RESTRICT;
ALTER TABLE evidence.review_aggregate
  ADD CONSTRAINT review_aggregate_domain_version_fk FOREIGN KEY (domain_version_id)
  REFERENCES config.domain_version (id) ON DELETE RESTRICT;

ALTER TABLE evidence.review_aggregate_member
  ADD CONSTRAINT ram_aggregate_fk FOREIGN KEY (aggregate_id)
  REFERENCES evidence.review_aggregate (id) ON DELETE RESTRICT;
ALTER TABLE evidence.review_aggregate_member
  ADD CONSTRAINT ram_summary_fk FOREIGN KEY (summary_id)
  REFERENCES evidence.review_summary (id) ON DELETE RESTRICT;

-- ── engine ──
ALTER TABLE engine.recommendation_run
  ADD CONSTRAINT rec_run_revision_fk FOREIGN KEY (revision_id)
  REFERENCES planning.plan_revision (id) ON DELETE RESTRICT;
ALTER TABLE engine.recommendation_run
  ADD CONSTRAINT rec_run_domain_version_fk FOREIGN KEY (domain_version_id)
  REFERENCES config.domain_version (id) ON DELETE RESTRICT;

ALTER TABLE engine.recommendation_candidate
  ADD CONSTRAINT rec_cand_run_fk FOREIGN KEY (run_id)
  REFERENCES engine.recommendation_run (id) ON DELETE RESTRICT;
ALTER TABLE engine.recommendation_candidate
  ADD CONSTRAINT rec_cand_requirement_fk FOREIGN KEY (requirement_id)
  REFERENCES planning.requirement (id) ON DELETE RESTRICT;
ALTER TABLE engine.recommendation_candidate
  ADD CONSTRAINT rec_cand_variant_fk FOREIGN KEY (variant_id)
  REFERENCES catalog.product_variant (id) ON DELETE RESTRICT;
ALTER TABLE engine.recommendation_candidate
  ADD CONSTRAINT rec_cand_observation_fk FOREIGN KEY (offer_observation_id)
  REFERENCES catalog.offer_observation (id) ON DELETE RESTRICT;

ALTER TABLE engine.candidate_evidence
  ADD CONSTRAINT cand_evidence_candidate_fk FOREIGN KEY (candidate_id)
  REFERENCES engine.recommendation_candidate (id) ON DELETE RESTRICT;
ALTER TABLE engine.candidate_evidence
  ADD CONSTRAINT cand_evidence_evidence_fk FOREIGN KEY (evidence_id)
  REFERENCES evidence.evidence (id) ON DELETE RESTRICT;

ALTER TABLE engine.validation_result
  ADD CONSTRAINT validation_result_run_fk FOREIGN KEY (run_id)
  REFERENCES engine.recommendation_run (id) ON DELETE RESTRICT;

ALTER TABLE engine.validation_target
  ADD CONSTRAINT validation_target_result_fk FOREIGN KEY (validation_result_id)
  REFERENCES engine.validation_result (id) ON DELETE RESTRICT;
ALTER TABLE engine.validation_target
  ADD CONSTRAINT validation_target_requirement_fk FOREIGN KEY (requirement_id)
  REFERENCES planning.requirement (id) ON DELETE RESTRICT;
ALTER TABLE engine.validation_target
  ADD CONSTRAINT validation_target_purchase_line_fk FOREIGN KEY (purchase_line_id)
  REFERENCES planning.purchase_line (id) ON DELETE RESTRICT;
ALTER TABLE engine.validation_target
  ADD CONSTRAINT validation_target_candidate_fk FOREIGN KEY (candidate_id)
  REFERENCES engine.recommendation_candidate (id) ON DELETE RESTRICT;

ALTER TABLE engine.validation_evidence
  ADD CONSTRAINT validation_evidence_result_fk FOREIGN KEY (validation_result_id)
  REFERENCES engine.validation_result (id) ON DELETE RESTRICT;
ALTER TABLE engine.validation_evidence
  ADD CONSTRAINT validation_evidence_evidence_fk FOREIGN KEY (evidence_id)
  REFERENCES evidence.evidence (id) ON DELETE RESTRICT;

ALTER TABLE engine.feedback_event
  ADD CONSTRAINT feedback_event_plan_fk FOREIGN KEY (plan_id)
  REFERENCES planning.plan (id) ON DELETE RESTRICT;
ALTER TABLE engine.feedback_event
  ADD CONSTRAINT feedback_event_revision_fk FOREIGN KEY (revision_id)
  REFERENCES planning.plan_revision (id) ON DELETE RESTRICT;
ALTER TABLE engine.feedback_event
  ADD CONSTRAINT feedback_event_rec_run_fk FOREIGN KEY (recommendation_run_id)
  REFERENCES engine.recommendation_run (id) ON DELETE RESTRICT;
ALTER TABLE engine.feedback_event
  ADD CONSTRAINT feedback_event_user_fk FOREIGN KEY (user_id)
  REFERENCES identity.app_user (id) ON DELETE RESTRICT;

-- ── notification ──
ALTER TABLE notification.price_watch
  ADD CONSTRAINT price_watch_revision_fk FOREIGN KEY (revision_id)
  REFERENCES planning.plan_revision (id) ON DELETE RESTRICT;
ALTER TABLE notification.price_watch
  ADD CONSTRAINT price_watch_purchase_line_fk FOREIGN KEY (purchase_line_id)
  REFERENCES planning.purchase_line (id) ON DELETE RESTRICT;

ALTER TABLE notification.price_watch_evaluation
  ADD CONSTRAINT pwe_watch_fk FOREIGN KEY (watch_id)
  REFERENCES notification.price_watch (id) ON DELETE RESTRICT;

ALTER TABLE notification.notification_event
  ADD CONSTRAINT notif_event_evaluation_fk FOREIGN KEY (evaluation_id)
  REFERENCES notification.price_watch_evaluation (id) ON DELETE RESTRICT;
ALTER TABLE notification.notification_event
  ADD CONSTRAINT notif_event_user_fk FOREIGN KEY (user_id)
  REFERENCES identity.app_user (id) ON DELETE RESTRICT;

-- ── dataset ──
ALTER TABLE dataset.review_sample
  ADD CONSTRAINT review_sample_subject_fk FOREIGN KEY (subject_id)
  REFERENCES evidence.review_subject (id) ON DELETE RESTRICT;
ALTER TABLE dataset.review_sample
  ADD CONSTRAINT review_sample_source_summary_fk FOREIGN KEY (source_summary_id)
  REFERENCES evidence.review_summary (id) ON DELETE RESTRICT;
ALTER TABLE dataset.review_sample
  ADD CONSTRAINT review_sample_source_revision_fk FOREIGN KEY (source_review_revision_id)
  REFERENCES community.review_revision (id) ON DELETE RESTRICT;
ALTER TABLE dataset.review_sample
  ADD CONSTRAINT review_sample_parent_fk FOREIGN KEY (parent_sample_id)
  REFERENCES dataset.review_sample (id) ON DELETE RESTRICT;
ALTER TABLE dataset.review_sample
  ADD CONSTRAINT review_sample_generation_run_fk FOREIGN KEY (generation_run_id)
  REFERENCES dataset.generation_run (id) ON DELETE RESTRICT;

ALTER TABLE dataset.review_label
  ADD CONSTRAINT review_label_sample_fk FOREIGN KEY (sample_id)
  REFERENCES dataset.review_sample (id) ON DELETE RESTRICT;
ALTER TABLE dataset.review_label
  ADD CONSTRAINT review_label_definition_fk FOREIGN KEY (label_definition_id)
  REFERENCES dataset.label_definition (id) ON DELETE RESTRICT;
ALTER TABLE dataset.review_label
  ADD CONSTRAINT review_label_annotator_fk FOREIGN KEY (annotator_user_id)
  REFERENCES identity.app_user (id) ON DELETE RESTRICT;
ALTER TABLE dataset.review_label
  ADD CONSTRAINT review_label_reviewer_fk FOREIGN KEY (reviewer_user_id)
  REFERENCES identity.app_user (id) ON DELETE RESTRICT;
