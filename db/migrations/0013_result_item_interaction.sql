-- 0013_result_item_interaction.sql — 결과 화면 장바구니 담기/빼기·수량·구매 시점
--
-- 지금까지 RecommendResultOut.items의 selected/qty/timing은 get_stored_result가 항상
-- True/1/"now"로 하드코딩해서 내보냈다 — PATCH /session/{id}/items/{item_id}가 없어서
-- 저장할 곳도 없었다. engine.recommendation_candidate에 세 컬럼을 추가해 실제로
-- 담기/빼기·수량·구매 시점을 저장한다. result(엔진이 고른 결과)와는 별개 개념이라
-- 컬럼을 분리한다 — result는 그대로 'selected'를 유지하고(엔진 추천 여부),
-- 새 selected는 "사용자가 장바구니에 담아뒀는가"를 뜻한다.

ALTER TABLE engine.recommendation_candidate
  ADD COLUMN selected boolean NOT NULL DEFAULT true,
  ADD COLUMN qty       integer NOT NULL DEFAULT 1 CHECK (qty BETWEEN 1 AND 99),
  ADD COLUMN timing    text    NOT NULL DEFAULT 'now' CHECK (timing IN ('now','soon','later'));
