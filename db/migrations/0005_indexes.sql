-- 0005_indexes.sql — 성능 인덱스 (명세서 각 테이블 "인덱스 제안" + FK 조인용)
-- PK/UNIQUE 선두 컬럼과 겹치는 것은 생략. 벡터 ANN 인덱스는 §10대로 초기엔 미적용.

-- ── identity ──
CREATE INDEX conversation_user_created_idx   ON identity.conversation (user_id, created_at DESC);
CREATE INDEX message_conv_created_idx        ON identity.message (conversation_id, created_at);

-- ── planning ──
CREATE INDEX plan_owner_updated_idx          ON planning.plan (owner_user_id, updated_at DESC);
CREATE INDEX plan_revision_plan_state_idx    ON planning.plan_revision (plan_id, state);
CREATE INDEX plan_revision_domain_ver_idx    ON planning.plan_revision (domain_version_id);
CREATE INDEX plan_condition_rev_status_idx   ON planning.plan_condition (revision_id, status);
CREATE INDEX plan_condition_message_idx      ON planning.plan_condition (source_message_id);
CREATE INDEX plan_node_rev_parent_pos_idx    ON planning.plan_node (revision_id, parent_id, position);
CREATE INDEX requirement_rev_status_idx      ON planning.requirement (revision_id, status);
CREATE INDEX requirement_node_idx            ON planning.requirement (node_id, revision_id);
CREATE INDEX owned_item_rev_idx             ON planning.owned_item (revision_id);
CREATE INDEX owned_item_variant_idx        ON planning.owned_item (variant_id);
CREATE INDEX purchase_line_rev_idx          ON planning.purchase_line (revision_id);
CREATE INDEX purchase_line_offer_idx        ON planning.purchase_line (offer_id);
CREATE INDEX alloc_rev_idx                  ON planning.fulfillment_allocation (revision_id);

-- ── catalog ──
CREATE INDEX product_brand_model_idx         ON catalog.product (brand, model);
CREATE INDEX product_type_status_idx         ON catalog.product (product_type, status);
CREATE INDEX product_category_parent_idx     ON catalog.product_category (parent_id);
CREATE INDEX pcm_category_product_idx        ON catalog.product_category_membership (category_id, product_id);
CREATE INDEX product_fact_prod_attr_idx      ON catalog.product_fact (product_id, attribute_key, status);
CREATE INDEX product_fact_evidence_idx       ON catalog.product_fact (evidence_id);
CREATE INDEX offer_variant_status_idx        ON catalog.offer (variant_id, status);
CREATE INDEX offer_merchant_idx             ON catalog.offer (merchant_id);
CREATE INDEX offer_obs_offer_observed_idx    ON catalog.offer_observation (offer_id, observed_at DESC);
CREATE INDEX offer_obs_source_idx           ON catalog.offer_observation (source_id);

-- ── assets ──
CREATE INDEX file_object_sha256_idx          ON assets.file_object (sha256);
CREATE INDEX file_object_status_idx          ON assets.file_object (storage_status, scan_status);
CREATE INDEX product_material_source_idx     ON assets.product_material (source_id, material_type, status);
CREATE INDEX material_revision_mat_status_idx ON assets.material_revision (material_id, status);
CREATE INDEX material_revision_file_idx      ON assets.material_revision (file_object_id);
CREATE INDEX material_applicability_prod_idx ON assets.material_applicability (product_id, variant_id, verified);
CREATE INDEX material_applicability_rev_idx  ON assets.material_applicability (revision_id);

-- ── rag ──
CREATE INDEX ingestion_job_status_created_idx ON rag.ingestion_job (status, created_at);
CREATE INDEX ingestion_job_rev_pipeline_idx   ON rag.ingestion_job (revision_id, pipeline_version);
CREATE INDEX document_chunk_search_gin        ON rag.document_chunk USING gin (search_vector);
CREATE INDEX chunk_embedding_profile_idx      ON rag.chunk_embedding (profile_id);
-- 규모 증가 시 (§10): 활성 profile·ready 상태 한정 부분 HNSW 검토
-- CREATE INDEX chunk_embedding_ann_idx ON rag.chunk_embedding
--   USING hnsw (embedding vector_cosine_ops) WHERE status = 'ready';
CREATE INDEX retrieval_run_rec_created_idx    ON rag.retrieval_run (recommendation_run_id, created_at);
CREATE INDEX retrieval_hit_chunk_idx          ON rag.retrieval_hit (chunk_id);

-- ── community ──
CREATE INDEX pc_build_owner_updated_idx      ON community.pc_build (owner_user_id, updated_at DESC);
CREATE INDEX pc_build_version_source_plan_idx ON community.pc_build_version (source_plan_revision_id);
CREATE INDEX pc_build_component_variant_idx  ON community.pc_build_component (variant_id, build_version_id);
CREATE INDEX review_subject_status_idx       ON community.review (subject_id, status, created_at DESC);
CREATE INDEX review_author_idx              ON community.review (author_user_id);
CREATE INDEX review_revision_review_no_idx   ON community.review_revision (review_id, revision_no DESC);
CREATE INDEX review_revision_domain_ver_idx  ON community.review_revision (domain_version_id);

-- ── evidence ──
CREATE INDEX evidence_source_idx             ON evidence.evidence (source_id);
CREATE INDEX evidence_retrieval_hit_idx      ON evidence.evidence (retrieval_hit_id);
CREATE INDEX evidence_review_aggregate_idx   ON evidence.evidence (review_aggregate_id);
CREATE INDEX evidence_status_valid_idx       ON evidence.evidence (status, valid_until);
CREATE INDEX review_summary_subject_idx      ON evidence.review_summary (subject_id, status, cleaning_status);
CREATE INDEX review_summary_source_idx       ON evidence.review_summary (source_id);
CREATE INDEX review_aggregate_subject_idx    ON evidence.review_aggregate (subject_id, source_scope, status, window_end DESC);
CREATE INDEX review_aggregate_domain_ver_idx ON evidence.review_aggregate (domain_version_id);
CREATE INDEX ram_summary_idx                 ON evidence.review_aggregate_member (summary_id);

-- ── engine ──
CREATE INDEX rec_run_revision_created_idx    ON engine.recommendation_run (revision_id, created_at DESC);
CREATE INDEX rec_run_domain_ver_idx          ON engine.recommendation_run (domain_version_id);
CREATE INDEX rec_cand_run_result_idx         ON engine.recommendation_candidate (run_id, result);
CREATE INDEX rec_cand_requirement_idx        ON engine.recommendation_candidate (requirement_id);
CREATE INDEX rec_cand_variant_idx            ON engine.recommendation_candidate (variant_id);
CREATE INDEX cand_evidence_evidence_idx      ON engine.candidate_evidence (evidence_id);
CREATE INDEX validation_result_run_status_idx ON engine.validation_result (run_id, status);
CREATE INDEX validation_target_result_idx    ON engine.validation_target (validation_result_id);
CREATE INDEX validation_evidence_evidence_idx ON engine.validation_evidence (evidence_id);
CREATE INDEX feedback_event_type_time_idx    ON engine.feedback_event (event_type, occurred_at);
CREATE INDEX feedback_event_plan_time_idx    ON engine.feedback_event (plan_id, occurred_at);
CREATE INDEX feedback_event_revision_idx     ON engine.feedback_event (revision_id);
CREATE INDEX feedback_event_rec_run_idx      ON engine.feedback_event (recommendation_run_id);

-- ── notification ──
CREATE INDEX price_watch_state_ends_idx      ON notification.price_watch (state, ends_at);
CREATE INDEX price_watch_revision_idx        ON notification.price_watch (revision_id);
CREATE INDEX pwe_watch_evaluated_idx         ON notification.price_watch_evaluation (watch_id, evaluated_at DESC);
CREATE INDEX notif_event_delivery_created_idx ON notification.notification_event (delivery_state, created_at);
CREATE INDEX notif_event_user_idx            ON notification.notification_event (user_id);

-- ── dataset ──
CREATE INDEX generation_run_status_created_idx ON dataset.generation_run (status, created_at);
CREATE INDEX review_sample_group_split_idx    ON dataset.review_sample (split_group_id, split);
CREATE INDEX review_sample_synth_status_idx   ON dataset.review_sample (is_synthetic, status, split);
CREATE INDEX review_sample_content_hash_idx   ON dataset.review_sample (content_hash);
CREATE INDEX review_sample_target_status_idx  ON dataset.review_sample (target_level, status);
CREATE INDEX review_sample_subject_idx        ON dataset.review_sample (subject_id);
CREATE INDEX review_sample_parent_idx         ON dataset.review_sample (parent_sample_id);
CREATE INDEX label_definition_status_task_idx ON dataset.label_definition (status, task_code);
CREATE INDEX review_label_def_status_idx      ON dataset.review_label (label_definition_id, review_status);
CREATE INDEX review_label_sample_created_idx  ON dataset.review_label (sample_id, created_at DESC);
