-- 0000_prereq.sql — 확장 · 스키마 · 공용 함수
-- RDS/Aurora PostgreSQL 16 호환. 슈퍼유저 전용 구문 없음.
--   · gen_random_uuid() 는 PG13+ 코어 (pgcrypto 불필요)
--   · vector 는 RDS 확장 허용목록 (RDS PG 15.2+/Aurora 15.3+)
--   · DDL 이벤트 트리거·커스텀 tablespace·COPY FROM PROGRAM 미사용

CREATE EXTENSION IF NOT EXISTS vector;

-- 스키마 12개 (테이블 생성 전에 모두 존재해야 함 — 교차 스키마 FK 때문)
CREATE SCHEMA IF NOT EXISTS config;
CREATE SCHEMA IF NOT EXISTS identity;
CREATE SCHEMA IF NOT EXISTS shared;
CREATE SCHEMA IF NOT EXISTS planning;
CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS assets;
CREATE SCHEMA IF NOT EXISTS rag;
CREATE SCHEMA IF NOT EXISTS community;
CREATE SCHEMA IF NOT EXISTS evidence;
CREATE SCHEMA IF NOT EXISTS engine;
CREATE SCHEMA IF NOT EXISTS notification;
CREATE SCHEMA IF NOT EXISTS dataset;

-- updated_at 자동 갱신 (모든 mutable 테이블에 트리거로 연결 → 0004_triggers.sql)
CREATE OR REPLACE FUNCTION shared.set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

-- ── 임베딩 차원 D ──────────────────────────────────────────────────────
-- 명세서 §8.2: 활성 임베딩 모델 1개 확정 후 그 차원으로 치환할 물리 설계 파라미터.
-- 모델 미확정 상태 → 아래 CREATE TABLE rag.chunk_embedding 의 vector(1024) 는 임시값.
-- 모델 확정 시 (1) 이 값 교체 (2) 다른 차원 도입 = 새 vector 컬럼·인덱스 마이그레이션.
