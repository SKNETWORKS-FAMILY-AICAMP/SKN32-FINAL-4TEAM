-- 0012_schema_reduction_safe_subset.sql — 축소 제안서 반영, 검증된 안전 항목만
--
-- 배경: docs/db/db_schema_reduction_proposal_2026-09-12.md (58→35, 8개 스키마 병합)를
-- 실행에 옮기는 첫 단계. 문서가 "코드 미사용"이라고 전제한 항목들을 실제로 하나씩
-- grep·row count로 재확인한 뒤, **지금 라이브로 동작 중인 기능을 건드리지 않는 항목만**
-- 이번 마이그레이션에 넣었다. 문서 작성(9/12) 이후 인증·리스트 확정/리포트/가격 알림·
-- 컴퓨터 추천 엔진이 실제로 구현돼서, 문서의 "코드 없음" 전제가 일부 더 이상 맞지 않는다.
--
-- 이번에 뺀 것(별도 계획 필요, 이 마이그레이션에 없음):
--   · config.domain + domain_version 병합 — engine_repo/plan_repo(4곳 JOIN)/session_service/
--     review_repo 등 세션 생성 핫패스가 domain_version_id를 그대로 쓰고 있어 리네임 범위가 큼.
--   · planning.plan_node 제거 → requirement.slot_key — 지금 라이브 컴퓨터 추천 엔진이
--     매 실행마다 ensure_node()로 실제 만들고 있고(256 rows), get_candidates()의 JOIN 대상.
--   · planning.owned_item + purchase_line → item 통합 — purchase_line은 152 rows,
--     list_service/notification_service/engine_repo/plan_repo 5개 파일이 실제로 쓰는
--     리스트 확정·리포트·가격 알림 기능의 핵심 테이블. owned_item(0 rows)만 이번에 뺀다.
--   · community.*(5→2), assets.*(4→2), evidence.source+evidence(→1) 병합 — 셋 다 0~1 rows에
--     코드 사용도 없어 안전하지만, 아직 구현 안 된 기능의 "미래 모양"을 지금 새로 설계해
--     넣는 일이라 서두르지 않는다. 스키마·행 개수는 그대로 두고 다음에 제대로 설계한다.
--
-- notification 스키마는 문서가 "완전 삭제"로 정리했지만, 이 세션에서 실제로
-- POST /lists/{id}/alert(가격 알림)를 구현·연결해 price_watch에 실 데이터(6 rows)가
-- 있다 — 문서보다 나중에 내려진 팀 결정을 따라 price_watch는 유지하고, 정말 미사용인
-- 나머지 2개 테이블만 뺀다.

-- ══════════════════════ identity: user_preference → app_user 흡수 ══════════════════════
-- 39 rows 실 데이터 — app_user와 1:1이라 컬럼으로 그대로 옮긴다. 코드 쪽(user_repo.py)도
-- 같이 고쳤다: signup 때 별도 INSERT 없이 app_user 컬럼 기본값 사용, withdraw 때 app_user
-- 자신의 컬럼을 초기화.
ALTER TABLE identity.app_user
  ADD COLUMN ui_settings           jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN notification_settings jsonb NOT NULL DEFAULT '{}'::jsonb;

UPDATE identity.app_user u
SET ui_settings = p.ui_settings, notification_settings = p.notification_settings
FROM identity.user_preference p
WHERE p.user_id = u.id;

DROP TABLE identity.user_preference CASCADE;

-- ══════════════════════ shared: unit 테이블만 제거, 스키마는 유지 ══════════════════════
-- 주의: shared 스키마 자체는 지우지 않는다 — shared.set_updated_at()이 이 마이그레이션
-- 시점 기준 30여 개 테이블(plan·product·recommendation_run·price_watch 등 전부 포함)의
-- BEFORE UPDATE 트리거로 걸려 있다(0000_prereq.sql, 0004_triggers.sql). 스키마를 통째로
-- 지우면 그 모든 테이블의 UPDATE가 "function shared.set_updated_at() does not exist"로
-- 즉시 깨진다 — 축소 제안서는 테이블 개수만 세느라 이 함수 존재를 고려하지 않았다.
-- shared.unit(4 rows) 자체는 code에서 SELECT/JOIN하는 곳이 없어(카탈로그 unit_code 컬럼들은
-- 값만 문자열로 저장, shared.unit을 참조 조회하지 않음) 안전하게 제거한다. FK 6개는
-- CASCADE로 제약만 사라지고 unit_code 컬럼·값은 그대로 남는다.
DROP TABLE shared.unit CASCADE;

-- ══════════════════════ catalog: product_category_membership 제거 ══════════════════════
-- 둘 다 0 rows, product_repo.py는 product_category(_membership)를 쿼리하지 않는다
-- (모듈 docstring에만 언급). 다대다 대신 product.category_id 단일 FK로 축소.
ALTER TABLE catalog.product ADD COLUMN category_id uuid;
ALTER TABLE catalog.product
  ADD CONSTRAINT product_category_fk FOREIGN KEY (category_id)
  REFERENCES catalog.product_category (id) ON DELETE RESTRICT;

DROP TABLE catalog.product_category_membership CASCADE;

-- ══════════════════════ engine: 근거/대상 연결 테이블 제거 ══════════════════════
-- 셋 다 0 rows. candidate_evidence/validation_target/validation_evidence는 라이브
-- 컴퓨터 추천 경로(execute_recommendation)에서 전혀 안 쓰고, 유아 전용
-- verify_and_explain_baby_candidate()(아직 API에 연결 안 됨)에서만 참조한다.
-- 나중에 필요하면 jsonb 컬럼에 직접 채우거나, 유아 경로를 실제로 짤 때 다시 설계한다.
ALTER TABLE engine.recommendation_candidate ADD COLUMN evidence_refs jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE engine.validation_result        ADD COLUMN issues        jsonb NOT NULL DEFAULT '[]'::jsonb;

DROP TABLE engine.candidate_evidence CASCADE;
DROP TABLE engine.validation_target CASCADE;
DROP TABLE engine.validation_evidence CASCADE;

-- ══════════════════════ notification: 미구현 발송 계열만 제거 ══════════════════════
-- price_watch(6 rows, 실사용)는 유지 — 위 배경 설명 참고. 나머지 2개는 0 rows이고
-- notification_repo.py도 모듈 docstring에만 이름이 있을 뿐 SQL이 없다.
DROP TABLE notification.notification_event CASCADE;
DROP TABLE notification.price_watch_evaluation CASCADE;

-- ══════════════════════ planning: 미사용 소유 물품·이행배분 제거 ══════════════════════
-- 둘 다 0 rows. purchase_line(152 rows, 실사용)과의 owned_item+purchase_line→item 통합은
-- 이번에 하지 않는다 — 위 배경 설명 참고.
DROP TABLE planning.fulfillment_allocation CASCADE;
DROP TABLE planning.owned_item CASCADE;

-- ══════════════════════ dataset: 스키마 전체 제거 ══════════════════════
-- 4개 테이블 전부 0 rows, 코드 참조 없음. 리뷰 클렌징 학습 데이터는 파일로 관리하기로
-- 팀 확인 완료(축소 제안서 §dataset).
DROP SCHEMA dataset CASCADE;
