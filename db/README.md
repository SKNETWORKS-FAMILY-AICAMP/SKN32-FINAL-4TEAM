# db/ — 스키마 마이그레이션 (Truefit)

[테이블_명세서 v4](../docs/db/table_spec.md) 의 58개 테이블 (12개 스키마) DDL. **RDS / Aurora PostgreSQL 16 호환** 을 전제로 작성.

## 실행

```bash
# 로컬 PG (컨테이너)
docker compose up -d
DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit python db/migrate.py up

# 현황
python db/migrate.py status
# RDS/Aurora 에 적용: DATABASE_URL 만 네트워크 DSN 으로 교체 (같은 파일, 같은 러너)
```

## 파일 (phase 순서)

| 파일 | 내용 |
|---|---|
| `0000_prereq.sql` | `CREATE EXTENSION vector` · 스키마 12개 · `shared.set_updated_at()` |
| `0001_tables.sql` | 58개 `CREATE TABLE` — 컬럼·PK·CHECK·DEFAULT. FK 없음 |
| `0002_unique.sql` | 단순/복합 UNIQUE (FK 타깃) · 부분/표현식/`NULLS NOT DISTINCT` UNIQUE 인덱스 |
| `0003_foreign_keys.sql` | 모든 FK (`ON DELETE RESTRICT`) — 복합 FK C01~C12 포함 |
| `0004_triggers.sql` | `updated_at` 자동 갱신 트리거 (updated_at 컬럼 있는 테이블 전부) |
| `0005_indexes.sql` | 성능 인덱스 (명세서 "인덱스 제안" + FK 조인용) · GIN(search_vector) |

phase 방식(테이블 전부 → 제약 전부 → 인덱스 전부)을 쓴 이유: 스키마 간 순환 참조가 있어서
(`assets.material_revision` ↔ `rag.ingestion_job`, `catalog` ↔ `evidence` ↔ `rag` ↔ `engine` ↔ `planning`).

## AWS 호환 원칙 (반영됨)

- `gen_random_uuid()` = PG13+ 코어 → `pgcrypto` 불필요
- 확장은 RDS 허용 목록만: `vector` (RDS PG 15.2+ / Aurora 15.3+)
- 슈퍼유저 전용 구문 없음: 커스텀 tablespace ✕, DDL 이벤트 트리거 ✕, `COPY FROM PROGRAM` ✕
- `updated_at`·(이후) 업무규칙 트리거는 일반 트리거 → RDS OK
- `timestamptz` = UTC 저장, 표시만 앱에서 Asia/Seoul
- 대용량 테이블(`offer_observation`·`retrieval_hit`·`feedback_event`·`notification_event`)은
  **파티션 키를 PK 에 포함하지 않았으나 시간 컬럼이 있음** — 최종에서 `pg_partman` 으로 월 range 파티션 (무중단)
- 커넥션 풀(PgBouncer/RDS Proxy) 전제: 세션 상태 의존 없음. 트랜잭션 내 `SET LOCAL` 만 사용할 것

## 벡터 차원 D

`rag.chunk_embedding.embedding vector(1024)` 의 `1024` 는 **임시값**. 명세서 §8.2:
활성 임베딩 모델 1개 확정 후 그 차원으로 치환. 차원이 바뀌면 새 vector 컬럼·인덱스 마이그레이션(별도 파일).

## DB 로 강제하는 것 vs 앱/트리거로 미루는 것

**DB (이 마이그레이션에 포함)**
- 모든 PK / FK(RESTRICT) / 단순·복합·부분 UNIQUE
- 단일 행 CHECK (enum, 범위, `num_nonnulls` XOR, 상태별 필수 컬럼)
- 복합 FK 로 같은 소속 강제: C01(plan↔revision) C02(node/req/alloc↔revision) C03(parent node)
  C04(observation↔offer) C05(variant↔product) C06(material current/active) C08(retrieval↔profile)
  C10(pc_build↔version) C12(review↔revision)
- `updated_at` 트리거

**앱 트랜잭션 / 업무규칙 트리거 (여기 미포함 — 다음 작업)**
- C03 깊이 제한(최상위 group→slot / 최상위 slot 만), C07 접근 필터, C09 근거 출처 일치,
  C11 소유권, C13 이중 집계 방지, **C14 게시/확정 불변성**, **C15 낙관적 잠금(lock_version)**,
  C16 배분 합계·통화 일관성, C18~C24 데이터셋·라벨·피드백 규칙
- 상태 전이 제한 (명세서 §9)
- JSONB 키·자료형·단위 검증 (명세서 §7)
- 한국어 tokenizer 확정 후 `document_chunk.search_vector` 생성 규칙

→ 이 항목들은 `src/repo/` 저장 서비스 계층 + 소수의 가드 트리거로 구현. 별도 마이그레이션(`0006_guard_triggers.sql` 등)으로 추가.
