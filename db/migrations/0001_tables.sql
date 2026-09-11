-- 0001_tables.sql — 58개 테이블 (컬럼 · PK · CHECK · DEFAULT). FK 없음.
-- FK/복합 UNIQUE → 0002, 0003. 트리거 → 0004. 성능 인덱스 → 0005.
-- 명세서: PlanBasket_테이블_명세서 v4. C## 는 6절 교차 무결성 항목.

-- ══════════════════════════════ config ══════════════════════════════
CREATE TABLE config.domain (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code        text NOT NULL,
  name        text NOT NULL,
  status      text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','disabled')),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE config.domain_version (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  domain_id         uuid NOT NULL,
  version_no        integer NOT NULL CHECK (version_no > 0),
  definition        jsonb NOT NULL,
  attribute_schema  jsonb NOT NULL,
  content_hash      text NOT NULL,
  published_at      timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now()
);

-- ══════════════════════════════ identity ══════════════════════════════
CREATE TABLE identity.app_user (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email_normalized   text NOT NULL,
  auth_subject       text NOT NULL,
  display_name       text NOT NULL,
  email_verified_at  timestamptz,
  status             text NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','deleted')),
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE identity.user_preference (
  user_id                uuid PRIMARY KEY,
  ui_settings            jsonb NOT NULL DEFAULT '{}'::jsonb,
  notification_settings  jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE identity.conversation (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id              uuid,
  guest_session_hash   text,
  expires_at           timestamptz,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CHECK (user_id IS NOT NULL OR guest_session_hash IS NOT NULL)
);

CREATE TABLE identity.message (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id    uuid NOT NULL,
  role               text NOT NULL CHECK (role IN ('user','assistant','system')),
  content            text NOT NULL,
  client_message_id  text NOT NULL,
  created_at         timestamptz NOT NULL DEFAULT now()
);

-- ══════════════════════════════ shared ══════════════════════════════
CREATE TABLE shared.unit (
  code            text PRIMARY KEY,
  dimension       text NOT NULL,
  base_unit_code  text,
  factor          numeric(20,8) NOT NULL DEFAULT 1 CHECK (factor > 0),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

-- ══════════════════════════════ planning ══════════════════════════════
CREATE TABLE planning.plan (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id      uuid NOT NULL,
  owner_user_id        uuid,
  name                 text NOT NULL,
  current_revision_id  uuid,                         -- C01: 생성 시 NULL, 같은 트랜잭션에서 설정
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE planning.plan_revision (
  id                   uuid NOT NULL DEFAULT gen_random_uuid(),
  plan_id              uuid NOT NULL,
  revision_no          integer NOT NULL,
  domain_version_id    uuid NOT NULL,
  state                text NOT NULL DEFAULT 'draft' CHECK (state IN ('draft','confirmed')),
  lock_version         integer NOT NULL DEFAULT 0,
  name_snapshot        text NOT NULL,
  confirmed_at         timestamptz,
  planned_purchase_at  timestamptz,
  confirmed_total      numeric(18,2),
  currency             char(3) NOT NULL DEFAULT 'KRW',
  pricing_policy       jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id),
  CHECK (revision_no > 0 AND lock_version >= 0),
  CHECK (confirmed_total IS NULL OR confirmed_total >= 0),
  CHECK (state <> 'confirmed' OR (confirmed_at IS NOT NULL AND confirmed_total IS NOT NULL))
);

CREATE TABLE planning.plan_condition (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  revision_id        uuid NOT NULL,
  condition_key      text NOT NULL,
  value              jsonb NOT NULL,
  origin             text NOT NULL CHECK (origin IN ('explicit','extracted','inferred')),
  source_message_id  uuid,
  supersedes_id      uuid,
  status             text NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded','deleted')),
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE planning.plan_node (
  id            uuid NOT NULL DEFAULT gen_random_uuid(),
  revision_id   uuid NOT NULL,
  parent_id     uuid,
  node_type     text NOT NULL CHECK (node_type IN ('group','slot')),
  template_key  text NOT NULL,
  name          text NOT NULL,
  position      integer NOT NULL DEFAULT 0,
  context       jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id)
);

CREATE TABLE planning.requirement (
  id              uuid NOT NULL DEFAULT gen_random_uuid(),
  revision_id     uuid NOT NULL,
  node_id         uuid NOT NULL,
  quantity        numeric(18,4) NOT NULL DEFAULT 1 CHECK (quantity > 0),
  unit_code       text NOT NULL DEFAULT 'each',
  required        boolean NOT NULL DEFAULT true,
  needed_at       timestamptz,
  timing_context  jsonb NOT NULL DEFAULT '{}'::jsonb,
  match_spec      jsonb NOT NULL DEFAULT '{}'::jsonb,
  status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active','excluded')),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id)
);

CREATE TABLE planning.owned_item (
  id                   uuid NOT NULL DEFAULT gen_random_uuid(),
  revision_id          uuid NOT NULL,
  variant_id           uuid,
  item_spec            jsonb NOT NULL DEFAULT '{}'::jsonb,
  quantity             numeric(18,4) NOT NULL DEFAULT 1 CHECK (quantity > 0),
  unit_code            text NOT NULL DEFAULT 'each',
  source_condition_id  uuid,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id),
  CHECK (variant_id IS NOT NULL OR item_spec <> '{}'::jsonb)
);

CREATE TABLE planning.purchase_line (
  id                       uuid NOT NULL DEFAULT gen_random_uuid(),
  revision_id              uuid NOT NULL,
  offer_id                 uuid NOT NULL,
  selected_observation_id  uuid NOT NULL,
  pack_count               integer NOT NULL DEFAULT 1,
  line_amount              numeric(18,2) NOT NULL,
  currency                 char(3) NOT NULL DEFAULT 'KRW',
  snapshot                 jsonb NOT NULL,
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id),
  CHECK (pack_count > 0 AND line_amount >= 0)
);

CREATE TABLE planning.fulfillment_allocation (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  revision_id       uuid NOT NULL,
  requirement_id    uuid NOT NULL,
  purchase_line_id  uuid,
  owned_item_id     uuid,
  quantity          numeric(18,4) NOT NULL DEFAULT 1,
  unit_code         text NOT NULL DEFAULT 'each',
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  CHECK (num_nonnulls(purchase_line_id, owned_item_id) = 1 AND quantity > 0)
);

-- ══════════════════════════════ catalog ══════════════════════════════
CREATE TABLE catalog.product (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name          text NOT NULL,
  brand         text NOT NULL,
  model         text NOT NULL,
  product_type  text NOT NULL,
  attributes    jsonb NOT NULL DEFAULT '{}'::jsonb,
  image_url     text,
  status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active','discontinued')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.product_variant (
  id             uuid NOT NULL DEFAULT gen_random_uuid(),
  product_id     uuid NOT NULL,
  variant_key    text NOT NULL,
  gtin           text,
  attributes     jsonb NOT NULL DEFAULT '{}'::jsonb,
  pack_quantity  numeric(18,4) NOT NULL DEFAULT 1 CHECK (pack_quantity > 0),
  unit_code      text NOT NULL DEFAULT 'each',
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id)
);

CREATE TABLE catalog.product_category (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  parent_id   uuid,
  code        text NOT NULL,
  name        text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.product_category_membership (
  product_id   uuid NOT NULL,
  category_id  uuid NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (product_id, category_id)
);

CREATE TABLE catalog.product_fact (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id     uuid NOT NULL,
  variant_id     uuid,
  attribute_key  text NOT NULL,
  value          jsonb NOT NULL,
  unit_code      text,
  evidence_id    uuid NOT NULL,
  observed_at    timestamptz NOT NULL,
  valid_until    timestamptz,
  status         text NOT NULL DEFAULT 'proposed'
                 CHECK (status IN ('proposed','verified','superseded','revoked')),
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.merchant (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  platform            text NOT NULL,
  external_seller_id  text NOT NULL,
  name                text NOT NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.offer (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  variant_id         uuid NOT NULL,
  merchant_id        uuid NOT NULL,
  external_offer_id  text NOT NULL,
  purchase_url       text NOT NULL,
  status             text NOT NULL DEFAULT 'active' CHECK (status IN ('active','sold_out','expired')),
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.offer_observation (
  id             uuid NOT NULL DEFAULT gen_random_uuid(),
  offer_id       uuid NOT NULL,
  source_id      uuid NOT NULL,
  observed_at    timestamptz NOT NULL,
  price          numeric(18,2),
  currency       char(3) NOT NULL DEFAULT 'KRW',
  stock_status   text NOT NULL CHECK (stock_status IN ('available','sold_out','unknown')),
  pricing_terms  jsonb NOT NULL DEFAULT '{}'::jsonb,
  quality_status text NOT NULL CHECK (quality_status IN ('valid','failed','stale')),
  valid_until    timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id),
  CHECK (price IS NULL OR price >= 0),
  CHECK (quality_status <> 'valid' OR price IS NOT NULL)
);

-- ══════════════════════════════ assets ══════════════════════════════
CREATE TABLE assets.file_object (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  bucket             text NOT NULL,
  object_key         text NOT NULL,
  storage_version    text NOT NULL,
  original_filename  text NOT NULL,
  mime_type          text NOT NULL,
  byte_size          bigint NOT NULL,
  sha256             text NOT NULL,
  access_scope       text NOT NULL DEFAULT 'internal' CHECK (access_scope IN ('public','internal')),
  use_policy         jsonb NOT NULL DEFAULT '{}'::jsonb,
  scan_status        text NOT NULL DEFAULT 'pending' CHECK (scan_status IN ('pending','clean','rejected')),
  storage_status     text NOT NULL DEFAULT 'pending'
                     CHECK (storage_status IN ('pending','available','quarantined','purged')),
  uploaded_by        uuid,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CHECK (byte_size > 0 AND length(sha256) = 64)
);

CREATE TABLE assets.product_material (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id            uuid NOT NULL,
  title                text NOT NULL,
  material_type        text NOT NULL
                       CHECK (material_type IN ('manual','spec_sheet','image','certification')),
  current_revision_id  uuid,
  status               text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','retired')),
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE assets.material_revision (
  id                    uuid NOT NULL DEFAULT gen_random_uuid(),
  material_id            uuid NOT NULL,
  revision_no            integer NOT NULL,
  file_object_id         uuid NOT NULL,
  source_url             text,
  language               text NOT NULL,
  issued_at              date,
  retrieved_at           timestamptz NOT NULL,
  active_ingestion_id    uuid,
  status                 text NOT NULL DEFAULT 'staged'
                         CHECK (status IN ('staged','published','superseded','revoked')),
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id)
);

CREATE TABLE assets.material_applicability (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  revision_id  uuid NOT NULL,
  product_id   uuid NOT NULL,
  variant_id   uuid,
  conditions   jsonb NOT NULL DEFAULT '{}'::jsonb,
  verified     boolean NOT NULL DEFAULT false,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);

-- ══════════════════════════════ rag ══════════════════════════════
CREATE TABLE rag.ingestion_job (
  id                    uuid NOT NULL DEFAULT gen_random_uuid(),
  revision_id           uuid NOT NULL,
  pipeline_version      text NOT NULL,
  idempotency_key       text NOT NULL,
  status                text NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued','running','ready','failed')),
  attempts              integer NOT NULL DEFAULT 0,
  started_at            timestamptz,
  completed_at          timestamptz,
  error_code            text,
  extraction_manifest   jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id)
);

CREATE TABLE rag.document_chunk (
  id             uuid NOT NULL DEFAULT gen_random_uuid(),
  ingestion_id   uuid NOT NULL,
  ordinal        integer NOT NULL CHECK (ordinal >= 0),
  content_type   text NOT NULL CHECK (content_type IN ('text','table','ocr','image_caption')),
  content_text   text NOT NULL,
  locator        jsonb NOT NULL,
  content_hash   text NOT NULL,
  confidence     numeric(5,4) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  review_status  text NOT NULL DEFAULT 'unreviewed'
                 CHECK (review_status IN ('unreviewed','verified','rejected')),
  search_vector  tsvector NOT NULL,               -- 앱이 설정한 tokenizer 로 채움 (§8.2 한국어 검증 대상)
  created_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id)
);

CREATE TABLE rag.embedding_profile (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_key            text NOT NULL,
  provider               text NOT NULL,
  model_name             text NOT NULL,
  model_revision         text NOT NULL,
  dimensions             integer NOT NULL CHECK (dimensions > 0),
  input_type             text NOT NULL DEFAULT 'text',
  preprocessing_version  text NOT NULL,
  distance_metric        text NOT NULL DEFAULT 'cosine' CHECK (distance_metric IN ('cosine')),
  status                 text NOT NULL DEFAULT 'staged'
                         CHECK (status IN ('staged','active','retired')),
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE rag.chunk_embedding (
  chunk_id     uuid NOT NULL,
  profile_id   uuid NOT NULL,
  embedding    vector(1024),                      -- D=1024 임시값 (§0000: 모델 확정 시 교체)
  input_hash   text NOT NULL,
  status       text NOT NULL DEFAULT 'ready' CHECK (status IN ('ready','revoked')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (chunk_id, profile_id),
  CHECK ((status = 'ready' AND embedding IS NOT NULL)
      OR (status = 'revoked' AND embedding IS NULL))
);

CREATE TABLE rag.retrieval_run (
  id                     uuid NOT NULL DEFAULT gen_random_uuid(),
  recommendation_run_id  uuid NOT NULL,
  profile_id             uuid NOT NULL,
  purpose                text NOT NULL CHECK (purpose IN ('recommendation','validation')),
  query_text             text NOT NULL,
  scope_snapshot         jsonb NOT NULL,
  retrieval_config       jsonb NOT NULL,
  status                 text NOT NULL DEFAULT 'running'
                         CHECK (status IN ('running','completed','failed')),
  completed_at           timestamptz,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id)
);

CREATE TABLE rag.retrieval_hit (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  retrieval_run_id      uuid NOT NULL,
  chunk_id              uuid NOT NULL,
  profile_id            uuid NOT NULL,
  rank_no               integer NOT NULL CHECK (rank_no > 0),
  vector_score          double precision,
  keyword_score         double precision,
  rerank_score          double precision,
  selected_for_context  boolean NOT NULL DEFAULT false,
  created_at            timestamptz NOT NULL DEFAULT now()
);

-- ══════════════════════════════ community ══════════════════════════════
CREATE TABLE community.pc_build (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id       uuid NOT NULL,
  name                text NOT NULL,
  current_version_id  uuid,
  visibility          text NOT NULL DEFAULT 'private' CHECK (visibility IN ('private','public')),
  status              text NOT NULL DEFAULT 'active' CHECK (status IN ('active','deleted')),
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE community.pc_build_version (
  id                        uuid NOT NULL DEFAULT gen_random_uuid(),
  build_id                  uuid NOT NULL,
  version_no                integer NOT NULL,
  source_plan_revision_id   uuid,
  state                     text NOT NULL DEFAULT 'draft' CHECK (state IN ('draft','published')),
  usage_status              text NOT NULL DEFAULT 'planned'
                            CHECK (usage_status IN ('planned','assembled_self_reported')),
  assembled_at              date,
  environment               jsonb NOT NULL DEFAULT '{}'::jsonb,
  configuration_hash        text,
  published_at              timestamptz,
  created_at                timestamptz NOT NULL DEFAULT now(),
  updated_at                timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id)
);

CREATE TABLE community.pc_build_component (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  build_version_id    uuid NOT NULL,
  slot_key            text NOT NULL,
  position            integer NOT NULL DEFAULT 0,
  variant_id          uuid NOT NULL,
  quantity            integer NOT NULL DEFAULT 1,
  component_snapshot  jsonb NOT NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  CHECK (quantity > 0 AND position >= 0)
);

CREATE TABLE community.review (
  id                   uuid NOT NULL DEFAULT gen_random_uuid(),
  author_user_id       uuid NOT NULL,
  subject_id           uuid NOT NULL,
  current_revision_id  uuid,
  status               text NOT NULL DEFAULT 'draft'
                       CHECK (status IN ('draft','published','hidden','deleted')),
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id)
);

CREATE TABLE community.review_revision (
  id                 uuid NOT NULL DEFAULT gen_random_uuid(),
  review_id          uuid NOT NULL,
  revision_no        integer NOT NULL,
  domain_version_id  uuid NOT NULL,
  rating             smallint NOT NULL CHECK (rating BETWEEN 1 AND 5),
  title              text NOT NULL,
  body               text NOT NULL,
  axis_scores        jsonb NOT NULL DEFAULT '{}'::jsonb,
  usage_context      jsonb NOT NULL DEFAULT '{}'::jsonb,
  moderation_status  text NOT NULL DEFAULT 'pending'
                     CHECK (moderation_status IN ('pending','approved','rejected','redacted')),
  published_at       timestamptz,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id)
);

-- ══════════════════════════════ evidence ══════════════════════════════
CREATE TABLE evidence.source (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name         text NOT NULL,
  source_type  text NOT NULL CHECK (source_type IN
               ('manufacturer','public_registry','merchant','external_review','first_party','derived')),
  base_url     text,
  rating_scale jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE evidence.evidence (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id            uuid NOT NULL,
  kind                 text NOT NULL CHECK (kind IN ('material','review_aggregate','external_fact')),
  retrieval_hit_id     uuid,
  review_aggregate_id  uuid,
  source_url           text,
  facts                jsonb NOT NULL DEFAULT '{}'::jsonb,
  citation_snapshot    jsonb NOT NULL,
  retrieved_at         timestamptz NOT NULL,
  valid_until          timestamptz,
  status               text NOT NULL DEFAULT 'active'
                       CHECK (status IN ('active','superseded','revoked')),
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CHECK (
    (kind = 'material'         AND retrieval_hit_id IS NOT NULL AND review_aggregate_id IS NULL     AND source_url IS NULL)
 OR (kind = 'review_aggregate' AND review_aggregate_id IS NOT NULL AND retrieval_hit_id IS NULL     AND source_url IS NULL)
 OR (kind = 'external_fact'    AND source_url IS NOT NULL AND retrieval_hit_id IS NULL AND review_aggregate_id IS NULL)
  )
);

CREATE TABLE evidence.review_subject (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id        uuid,
  variant_id        uuid,
  offer_id          uuid,
  build_version_id  uuid,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  CHECK (num_nonnulls(product_id, variant_id, offer_id, build_version_id) = 1)
);

CREATE TABLE evidence.review_summary (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_id           uuid NOT NULL,
  source_id            uuid NOT NULL,
  origin               text NOT NULL CHECK (origin IN ('external','first_party')),
  external_review_key  text,
  original_url         text,
  review_revision_id   uuid,
  summary              text NOT NULL,
  normalized_rating    numeric(3,2),
  collected_at         timestamptz NOT NULL,
  processing_version   text NOT NULL,
  cleaning_status      text NOT NULL CHECK (cleaning_status IN ('retained','excluded','pending')),
  exclusion_reason     text,
  status               text NOT NULL DEFAULT 'active'
                       CHECK (status IN ('active','superseded','revoked')),
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CHECK (
    (origin = 'external'    AND external_review_key IS NOT NULL AND original_url IS NOT NULL AND review_revision_id IS NULL)
 OR (origin = 'first_party' AND review_revision_id IS NOT NULL AND external_review_key IS NULL)
  ),
  CHECK (normalized_rating IS NULL OR (normalized_rating >= 0 AND normalized_rating <= 5))
);

CREATE TABLE evidence.review_aggregate (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_id         uuid NOT NULL,
  domain_version_id  uuid NOT NULL,
  source_scope       text NOT NULL CHECK (source_scope IN ('external','first_party','combined')),
  processing_version text NOT NULL,
  window_start       timestamptz NOT NULL,
  window_end         timestamptz NOT NULL,
  analyzed_count     integer NOT NULL DEFAULT 0,
  excluded_count     integer NOT NULL DEFAULT 0,
  retained_count     integer NOT NULL DEFAULT 0,
  ratings            jsonb NOT NULL DEFAULT '{}'::jsonb,
  axis_scores        jsonb NOT NULL DEFAULT '{}'::jsonb,
  status             text NOT NULL DEFAULT 'building'
                     CHECK (status IN ('building','ready','stale','revoked')),
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CHECK (analyzed_count = excluded_count + retained_count AND excluded_count >= 0 AND retained_count >= 0),
  CHECK (window_end >= window_start)
);

CREATE TABLE evidence.review_aggregate_member (
  aggregate_id  uuid NOT NULL,
  summary_id    uuid NOT NULL,
  disposition   text NOT NULL CHECK (disposition IN ('retained','excluded')),
  weight        numeric(8,4) NOT NULL DEFAULT 1 CHECK (weight > 0),
  created_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (aggregate_id, summary_id)
);

-- ══════════════════════════════ engine ══════════════════════════════
CREATE TABLE engine.recommendation_run (
  id                 uuid NOT NULL DEFAULT gen_random_uuid(),
  revision_id        uuid NOT NULL,
  domain_version_id  uuid NOT NULL,
  input_snapshot     jsonb NOT NULL,
  input_hash         text NOT NULL,
  draft_lock_version integer NOT NULL,
  engine_versions    jsonb NOT NULL,
  status             text NOT NULL DEFAULT 'queued'
                     CHECK (status IN ('queued','running','completed','failed','stale')),
  completed_at       timestamptz,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id)
);

CREATE TABLE engine.recommendation_candidate (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id                 uuid NOT NULL,
  requirement_id         uuid NOT NULL,
  variant_id             uuid NOT NULL,
  offer_observation_id   uuid,
  result                 text NOT NULL CHECK (result IN ('pending','passed','rejected','selected')),
  score                  numeric(8,4),
  score_method_version   text,
  reason                 text,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now(),
  CHECK (score IS NULL OR score_method_version IS NOT NULL)
);

CREATE TABLE engine.candidate_evidence (
  candidate_id  uuid NOT NULL,
  evidence_id   uuid NOT NULL,
  claim_key     text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (candidate_id, evidence_id, claim_key)
);

CREATE TABLE engine.validation_result (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id            uuid NOT NULL,
  rule_key          text NOT NULL,
  rule_version      text NOT NULL,
  executor_version  text NOT NULL,
  status            text NOT NULL CHECK (status IN ('pass','fail','unknown','not_applicable')),
  severity          text NOT NULL CHECK (severity IN ('info','warning','critical')),
  measured_values   jsonb NOT NULL DEFAULT '{}'::jsonb,
  threshold         jsonb NOT NULL DEFAULT '{}'::jsonb,
  message           text NOT NULL,
  checked_at        timestamptz NOT NULL,
  created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE engine.validation_target (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  validation_result_id  uuid NOT NULL,
  requirement_id        uuid,
  purchase_line_id      uuid,
  candidate_id          uuid,
  created_at            timestamptz NOT NULL DEFAULT now(),
  CHECK (num_nonnulls(requirement_id, purchase_line_id, candidate_id) = 1)
);

CREATE TABLE engine.validation_evidence (
  validation_result_id  uuid NOT NULL,
  evidence_id           uuid NOT NULL,
  created_at            timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (validation_result_id, evidence_id)
);

CREATE TABLE engine.feedback_event (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  plan_id                uuid NOT NULL,
  revision_id            uuid NOT NULL,
  recommendation_run_id  uuid,
  user_id                uuid,
  event_type             text NOT NULL CHECK (event_type IN
                         ('recommendation_shown','item_replaced','item_removed','plan_confirmed')),
  event_key              text NOT NULL,
  payload                jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at            timestamptz NOT NULL,
  created_at             timestamptz NOT NULL DEFAULT now(),
  CHECK (event_type <> 'recommendation_shown' OR recommendation_run_id IS NOT NULL)
);

-- ══════════════════════════════ notification ══════════════════════════════
CREATE TABLE notification.price_watch (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  revision_id           uuid NOT NULL,
  purchase_line_id      uuid,
  target_amount         numeric(18,2) NOT NULL CHECK (target_amount >= 0),
  currency              char(3) NOT NULL DEFAULT 'KRW',
  pricing_policy        jsonb NOT NULL,
  state                 text NOT NULL DEFAULT 'active' CHECK (state IN ('active','paused','expired')),
  ends_at               timestamptz NOT NULL,
  last_condition_state  text NOT NULL DEFAULT 'unknown'
                        CHECK (last_condition_state IN ('unknown','above','reached')),
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE notification.price_watch_evaluation (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  watch_id        uuid NOT NULL,
  evaluated_at    timestamptz NOT NULL,
  amount          numeric(18,2),
  currency        char(3) NOT NULL DEFAULT 'KRW',
  status          text NOT NULL CHECK (status IN ('complete','stale','unavailable')),
  target_reached  boolean,
  breakdown       jsonb NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  CHECK (status <> 'complete' OR (amount IS NOT NULL AND target_reached IS NOT NULL))
);

CREATE TABLE notification.notification_event (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  evaluation_id     uuid NOT NULL,
  user_id           uuid NOT NULL,
  channel           text NOT NULL DEFAULT 'email' CHECK (channel IN ('email')),
  dedupe_key        text NOT NULL,
  delivery_state    text NOT NULL DEFAULT 'pending' CHECK (delivery_state IN ('pending','sent','failed')),
  attempts          integer NOT NULL DEFAULT 0,
  sent_at           timestamptz,
  read_at           timestamptz,
  payload_snapshot  jsonb NOT NULL,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);

-- ══════════════════════════════ dataset ══════════════════════════════
CREATE TABLE dataset.generation_run (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  method             text NOT NULL CHECK (method IN ('llm','template','paraphrase','back_translation')),
  generator_name     text NOT NULL,
  generator_version  text NOT NULL,
  recipe_version     text NOT NULL,
  generation_config  jsonb NOT NULL,
  idempotency_key    text NOT NULL,
  status             text NOT NULL DEFAULT 'queued'
                     CHECK (status IN ('queued','running','completed','failed')),
  started_at         timestamptz,
  finished_at        timestamptz,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at),
  CHECK (status NOT IN ('completed','failed') OR (started_at IS NOT NULL AND finished_at IS NOT NULL))
);

CREATE TABLE dataset.review_sample (
  id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  is_synthetic                boolean NOT NULL,
  subject_id                  uuid,
  target_level                text NOT NULL CHECK (target_level IN ('component','build','offer','unknown')),
  source_summary_id           uuid,
  source_review_revision_id   uuid,
  parent_sample_id            uuid,
  external_dataset_ref        jsonb,
  purchase_verified           boolean,
  purchase_verification_ref   jsonb,
  review_posted_at            timestamptz,
  analysis_snapshot           jsonb NOT NULL DEFAULT '{}'::jsonb,
  generation_run_id           uuid,
  generation_item_key         text,
  content_kind                text NOT NULL CHECK (content_kind IN
                              ('summary','first_party_body','external_summary','synthetic_body')),
  content_text                text,
  content_hash                text NOT NULL,
  context_snapshot            jsonb NOT NULL DEFAULT '{}'::jsonb,
  split_group_id              uuid NOT NULL,          -- 그룹 식별자, FK 아님 (§55)
  split                       text NOT NULL DEFAULT 'unassigned'
                              CHECK (split IN ('unassigned','train','validation','test')),
  status                      text NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending','approved','rejected','revoked')),
  created_at                  timestamptz NOT NULL DEFAULT now(),
  updated_at                  timestamptz NOT NULL DEFAULT now(),
  -- C17: 실제/합성 원천 XOR + 생성 FK 필수 여부
  CHECK (
    (is_synthetic = false
       AND num_nonnulls(source_summary_id, source_review_revision_id, external_dataset_ref) = 1
       AND parent_sample_id IS NULL AND generation_run_id IS NULL AND generation_item_key IS NULL)
 OR (is_synthetic = true
       AND source_summary_id IS NULL AND source_review_revision_id IS NULL AND external_dataset_ref IS NULL
       AND parent_sample_id IS NOT NULL AND generation_run_id IS NOT NULL AND generation_item_key IS NOT NULL)
  ),
  CHECK (parent_sample_id <> id),
  -- C24: 합성은 실구매 표시·검증 참조·등록 시각 NULL
  CHECK (is_synthetic = false
         OR (purchase_verified IS NULL AND purchase_verification_ref IS NULL AND review_posted_at IS NULL)),
  CHECK (purchase_verified IS NULL OR purchase_verification_ref IS NOT NULL),
  CHECK (status = 'revoked' OR (content_text IS NOT NULL AND btrim(content_text) <> ''))
);

CREATE TABLE dataset.label_definition (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_code     text NOT NULL,
  version_no    integer NOT NULL CHECK (version_no > 0),
  name          text NOT NULL,
  target_level  text NOT NULL CHECK (target_level IN ('component','build','offer','unknown','any')),
  value_schema  jsonb NOT NULL,
  guidelines    text NOT NULL,
  status        text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','retired')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE dataset.review_label (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sample_id            uuid NOT NULL,
  label_definition_id  uuid NOT NULL,
  revision_no          integer NOT NULL CHECK (revision_no > 0),
  label_value          jsonb,
  label_origin         text NOT NULL CHECK (label_origin IN ('human','rule','model','imported')),
  labeler_ref          text NOT NULL,
  labeling_config      jsonb NOT NULL DEFAULT '{}'::jsonb,
  annotator_user_id    uuid,
  confidence           numeric(5,4) CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
  review_status        text NOT NULL DEFAULT 'pending'
                       CHECK (review_status IN ('pending','approved','rejected','superseded','revoked')),
  reviewer_user_id     uuid,
  reviewed_at          timestamptz,
  evidence_snapshot    jsonb NOT NULL,
  review_note          text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CHECK (review_status NOT IN ('approved','rejected','superseded')
         OR (reviewer_user_id IS NOT NULL AND reviewed_at IS NOT NULL)),
  CHECK (label_origin <> 'human' OR annotator_user_id IS NOT NULL),
  CHECK (review_status = 'revoked' OR label_value IS NOT NULL)
);
