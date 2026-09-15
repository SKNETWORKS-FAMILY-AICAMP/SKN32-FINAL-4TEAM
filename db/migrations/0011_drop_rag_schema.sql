-- 0011_drop_rag_schema.sql — rag 스키마 전체 삭제 (별도 벡터DB로 분리, 팀 확정)
--
-- 배경: docs/db/db_schema_reduction_proposal_2026-09-12.md §rag 항목 — 멘토 피드백
-- "벡터를 RDB에 넣는 설계는 틀렸다"에 따라 "RAG는 별도 벡터DB를 쓴다"는 방향을
-- 가정으로 정리해 뒀던 항목. 비정형 데이터(청크·임베딩·검색 이력)가 커질수록
-- RDB에 같이 두면 문제가 된다는 판단으로 팀이 최종 확정.
--
-- 6개 테이블(ingestion_job, document_chunk, embedding_profile, chunk_embedding,
-- retrieval_run, retrieval_hit) 전체 삭제. evidence.evidence.retrieval_hit_id의
-- FK(evidence_retrieval_hit_fk)만 CASCADE로 같이 제거되고 evidence.evidence
-- 테이블 자체나 다른 컬럼은 그대로 남는다.
--
-- 영향 범위: src/repo/rag_repo.py, src/rag/*, tests/test_rag*.py 는 이 스키마가
-- 없으면 더 이상 동작하지 않는다 — RAG를 다시 구현할 때 별도 벡터DB 클라이언트로
-- 새로 짠다. 지금 라이브로 연결된 컴퓨터 도메인 추천 경로([3-C] verify_build,
-- [5] stage5_explain)는 이 스키마를 쓰지 않으므로 영향 없음.

DROP SCHEMA rag CASCADE;
