-- 0004_triggers.sql — updated_at 자동 갱신 트리거
-- updated_at 컬럼이 있는 모든 테이블에 shared.set_updated_at() BEFORE UPDATE 트리거 연결.
-- (게시/확정 불변성 C14, 낙관적 잠금 C15 등 업무 규칙 트리거는 이 마이그레이션 범위 밖 — db/README 참조)

DO $$
DECLARE
  t text;
  tables text[] := ARRAY[
    'config.domain',
    'identity.app_user','identity.user_preference','identity.conversation',
    'shared.unit',
    'planning.plan','planning.plan_revision','planning.plan_condition','planning.plan_node',
    'planning.requirement','planning.owned_item','planning.purchase_line','planning.fulfillment_allocation',
    'catalog.product','catalog.product_variant','catalog.product_category','catalog.product_fact',
    'catalog.merchant','catalog.offer',
    'assets.file_object','assets.product_material','assets.material_revision','assets.material_applicability',
    'rag.ingestion_job','rag.embedding_profile','rag.retrieval_run',
    'community.pc_build','community.pc_build_version','community.review','community.review_revision',
    'evidence.source','evidence.evidence','evidence.review_subject','evidence.review_summary','evidence.review_aggregate',
    'engine.recommendation_run','engine.recommendation_candidate',
    'notification.price_watch','notification.notification_event',
    'dataset.generation_run','dataset.review_sample','dataset.label_definition','dataset.review_label'
  ];
BEGIN
  FOREACH t IN ARRAY tables LOOP
    EXECUTE format(
      'CREATE TRIGGER set_updated_at BEFORE UPDATE ON %s
         FOR EACH ROW EXECUTE FUNCTION shared.set_updated_at()', t);
  END LOOP;
END;
$$;
