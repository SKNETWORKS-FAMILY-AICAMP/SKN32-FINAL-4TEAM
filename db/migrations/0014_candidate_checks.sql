-- 0014_candidate_checks.sql — 품목별 "구매 전 확인"(checks) 저장 컬럼
--
-- get_stored_result가 지금까지 items[].checks를 {"status":"pending","text":None}로
-- 하드코딩만 하고 있었다 — [3-C] 개별 품목 확인 문장 자리인데 채우는 코드가 아예 없었다.
-- reason/reason_status와 완전히 같은 패턴으로 checks/checks_status를 추가한다 — 부품
-- 사용 가이드 RAG 검색(src/rag/care_guides.py)이 [5]와 같은 시점에 채운다.

ALTER TABLE engine.recommendation_candidate
  ADD COLUMN checks        text,
  ADD COLUMN checks_status text NOT NULL DEFAULT 'pending',
  ADD CONSTRAINT recommendation_candidate_checks_status_check
    CHECK (checks_status IN ('pending','ready','failed')),
  ADD CONSTRAINT recommendation_candidate_checks_content_check
    CHECK ((checks_status = 'ready') = (checks IS NOT NULL));
