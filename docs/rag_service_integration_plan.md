# RAG 사용자 서비스 흐름 통합 실행 계획

## 에이전트 임무

현재 독립적으로 동작하는 설명서 RAG를 실제 사용자 서비스 흐름에 끝까지 연결한다.
완료 시 사용자가 세션에서 유아용품 조건을 입력하고 추천을 실행하면, 서버가 추천 실행 ID와
정확한 상품·옵션 범위로 설명서 근거를 검색하고, 검증 및 설명에 채택한 인용을 저장한 뒤,
동일 사용자가 결과 조회 API에서 답변·근거·불확실성을 확인할 수 있어야 한다.

이 문서는 구현 지시서다. 기존 테스트를 통과시키는 것만으로 완료 처리하지 말고 아래의 완료
조건을 실제 HTTP 요청과 PostgreSQL 통합 테스트로 증명한다.

## 현재 상태와 핵심 간극

- `src/rag/service.py`, `src/repo/rag_repo.py`에는 실제 pgvector 검색, 인용 직전 권한 재검사,
  검색 실행 추적 기능이 있다.
- `src/engine/stage3c_verify.py::verify_baby_manual`과
  `src/engine/stage5_explain.py::explain_manual`은 실제 RAG 소비 함수지만 운영 호출자가 없다.
- `src/services/recommendation_service.py::run_for_revision`과 `get_result`는 미구현이다.
- `src/routers/session.py`의 세션·조건·추천·결과 엔드포인트는 미구현이다.
- `src/pipeline.py`의 유아용 `per_item` 분기는 미구현이다.
- `src/repo/engine_repo.py`, `src/repo/plan_repo.py`의 필요한 메서드는 인터페이스만 있고
  구현이 없다.
- 현재 `/dev/run`은 시나리오 및 인메모리 코퍼스 기반 데모다. 운영 RAG 통합의 성공 기준으로
  사용하지 않는다.

## 반드시 지킬 계약

1. RAG 검색마다 실제 `engine.recommendation_run.id`를
   `SearchRequest.recommendation_run_id`로 전달한다. 독립 검색용 가짜 실행 ID를 만들지 않는다.
2. 검색 범위에 `domain`, `product_key`, `variant_key`, `market`, `language`, `corpus`를 명시한다.
   선택된 후보와 다른 상품 또는 옵션의 근거를 섞지 않는다.
3. HTTP에서 받은 추천 실행 ID를 바로 신뢰하지 않는다. 현재 principal이 소유한 plan과
   revision에 속하는지 서버에서 확인한 후 RAG를 호출한다.
4. 검색 점수는 안전성 판정이 아니다. `eligibility_status=pass`도 부분 설명서 전체의 안전
   통과로 승격하지 않는다. `coverage_status=partial`, 미검수, 입력 누락, 조건 충돌은 기존
   RAG 계약대로 보수적으로 표시한다.
5. 답변에는 실제로 채택된 `evidence_id`와 원문 locator를 포함한다. 채택한 근거는
   `candidate_evidence` 또는 `validation_evidence`에 연결한다.
6. 검색 오류를 `no_evidence`로 바꾸지 않는다. `success`, `no_evidence`, `error`를 API와
   저장 상태에서 구분한다.
7. `MOCK_MODE`는 개발 시나리오에만 영향을 주게 한다. 운영 추천 경로는
   `evidence_search()`의 전역 미니 코퍼스에 의존하지 않고 `RagService`를 명시적으로 주입한다.
8. 데이터베이스 트랜잭션 안에서 외부 임베딩 호출을 오래 유지하지 않는다. 추천 실행 생성,
   RAG 호출, 결과 저장의 경계를 명확히 하며 실패 상태를 남긴다.
9. 현재 게시 버전, 공개 범위, RAG·발췌 허용, 파일 검사 상태, 철회 상태를 우회하지 않는다.
10. 실제 설명서에 없는 절차나 기능을 생성하지 않는다. 설명은 근거 발췌 중심으로 유지한다.

## 목표 서비스 흐름

```text
POST /session
  -> conversation + plan + draft plan_revision 생성
  -> browser_token 또는 로그인 사용자에게 소유권 부여

POST /session/{list_id}/category, /message, /answer, /slot
  -> draft revision 조건 저장
  -> required_inputs 충족 여부 반환

POST /session/{list_id}/recommend
  -> principal 및 list 소유권 확인
  -> 현재 draft revision과 lock_version 읽기
  -> engine.recommendation_run 생성
  -> 유아용 후보 생성·필터·순위화
  -> 후보별 product_key + variant_key 결정
  -> 후보별 SearchRequest 생성
  -> verify_baby_manual로 조건 검증
  -> explain_manual로 근거 기반 설명 생성
  -> 후보·검증·채택 근거 저장
  -> lock_version 재확인 후 recommendation_run 완료
  -> status=done 응답

GET /session/{list_id}/result
  -> principal 및 list 소유권 재확인
  -> 최신 또는 지정된 recommendation_run 조회
  -> 후보, 검증 상태, 설명, 인용, coverage/error 상태 반환
```

## 구현 단계

### 1. 서비스 경계와 데이터 계약 확정

- `src/schemas.py`에서 mutable 기본값을 `Field(default_factory=...)`로 교체한다.
- 추천 응답에 최소한 다음 필드를 명시적인 Pydantic 모델로 정의한다.
  - `recommendation_run_id`, `list_id`, `revision_id`, `status`
  - 후보별 `product_key`, `variant_key`, 상품명, 가격
  - `eligibility_status`, `verification_status`, `coverage_status`, `reason`
  - 근거별 `evidence_id`, `text`, `locator`, `file_sha256`, `review_status`
  - RAG 실패 시 공개 가능한 `error_code`
- 내부 DTO와 HTTP DTO 사이에 변환 함수를 두고 DB 행을 그대로 응답하지 않는다.
- 동기 실행을 우선 구현한다. 현재 워커 인프라가 완성되지 않았으므로 `running`을 반환하고
  실제 작업을 시작하지 않는 형태는 금지한다. 후속 비동기화가 가능하도록 run 상태는 유지한다.

완료 조건: OpenAPI에 구체적인 추천·근거 응답 스키마가 나타나며 임의 `dict` 의존이 줄어든다.

### 2. 세션 소유권과 계획 리비전 최소 구현

- `src/auth/deps.py`에 JWT 또는 browser token에서 `Principal`을 만드는 FastAPI dependency를
  구현한다. 개발용 기본 principal을 자동 부여하지 않는다.
- `src/repo/plan_repo.py`에서 이번 흐름에 필요한 생성, 현재 revision 조회, 조건 upsert,
  `load_full`, lock version 조회를 실제 SQL로 구현한다.
- `src/services/session_service.py`에서 세션 생성, 카테고리 선택, 조건 갱신,
  `can_recommend` 계산을 구현한다.
- 모든 `/session/{list_id}/*` 요청에서 사용자 ID 또는 browser token이 해당 conversation/plan을
  소유하는지 확인한다. 존재 여부를 타 사용자에게 노출하지 않도록 일관된 404 또는 정책상 정한
  응답을 사용한다.
- 이미 존재하는 DB 제약 C01, C14, C15를 서비스 코드에서 다시 의미 있게 처리한다.

완료 조건: 사용자 A가 만든 list를 사용자 B가 수정·추천·조회할 수 없고, 조건이 부족하면
추천 요청이 422로 종료되며 recommendation_run을 만들지 않는다.

### 3. 추천 실행 및 결과 저장소 구현

- `src/repo/engine_repo.py`의 다음 메서드를 우선 구현한다.
  - `start_run`, `complete_run`
  - `add_candidate`, `link_candidate_evidence`
  - `add_validation`, `link_validation_target`, `link_validation_evidence`
  - 결과 조회에 필요한 명시적 read 메서드
- `start_run`은 revision, domain version, 입력 snapshot/hash, draft lock version,
  엔진 버전을 저장한다.
- `complete_run`은 허용된 상태 전이를 강제하고 완료·실패 정보를 저장한다. 필요하면 기존
  스키마 범위에서 공개 가능한 오류 코드를 남길 방법을 추가하되 원문 예외나 자격증명을 저장하지 않는다.
- 결과 적용 직전에 현재 draft `lock_version`이 시작 시점과 같은지 확인한다. 다르면 오래된 결과를
  현재 결과로 표시하지 말고 충돌 상태로 끝낸다.

완료 조건: 추천 한 번에 정확히 한 recommendation_run이 생성되고, 성공과 실패 모두 추적 가능하며,
중간 예외가 완료 상태로 기록되지 않는다.

### 4. 유아용 실제 파이프라인 구현

- `src/pipeline.py`에서 시나리오 전용 `run_pipeline()`과 DB 기반 서비스 파이프라인을 분리한다.
  DB 기반 함수는 scenario JSON이나 `_MINI_CORPUS`를 읽지 않는다.
- plan revision의 조건을 `Slots`와 `RequirementSpec`으로 변환한다.
- 카탈로그 후보에 RAG가 요구하는 안정적인 `product_key`, `variant_key`, 시장·언어 정보를
  포함한다. 식별자 매핑이 없으면 해당 후보를 설명서 검증 대상으로 보내지 말고 사유를 기록한다.
- 유아 분기는 각 후보를 독립적으로 검증한다. 최소 현재 구현된 좌석 조건인
  `age_months`, `weight_kg`, `independent_sitting`을 `verify_baby_manual`에 전달한다.
- 검증 결과가 `fail`이면 추천 제외 또는 명확한 탈락 상태로 처리한다. `unknown`은 자동 통과시키지
  말고 정책에 따라 후보 유지 여부와 사용자 표시를 분리한다.
- 예산 배분 결과를 `BasketResult`로 만들고 선택 후보와 검증 결과의 연결을 보존한다.

완료 조건: `baby` 요청이 `NotImplementedError` 없이 후보별 검증과 예산 배분을 마친다.

### 5. RAG를 검증 및 설명 단계에 주입

- 요청 단위 DB connection/repository 수명주기를 정의하고 `RagService(RagRepo(conn), embedder)`를
  추천 서비스에서 생성해 파이프라인에 명시적으로 전달한다.
- 각 후보에 아래 형태의 `SearchRequest`를 만든다.

```python
SearchRequest(
    domain="baby",
    product_key=candidate.product_key,
    variant_key=candidate.variant_key,
    query=query,
    market=candidate.market,
    language="ko",
    corpus="real",  # 합성 데이터만 쓰는 명시적 테스트에서는 synthetic
    purpose="validation",  # 설명 생성은 recommendation
    recommendation_run_id=str(run_id),
    context=applicability_context,
)
```

- 검증 질의와 설명 질의는 목적과 채택 근거를 별도로 기록한다. 같은 근거를 재사용해도 각 retrieval
  run의 추적 관계를 유지한다.
- `verify_baby_manual`의 evidence를 `validation_evidence`에 연결한다.
- `explain_manual`에서 실제로 선택된 evidence를 해당 candidate의 `candidate_evidence`에 연결한다.
- 답변 반환 직전에 `resolve_evidence` 또는 동등한 기존 재검사를 거친 근거만 직렬화한다.
- 한 후보의 RAG 오류가 전체 추천 실행을 실패시킬지 해당 후보만 unknown으로 만들지는 명시적인
  정책 함수로 결정한다. 안전 조건 검증 오류는 최소한 해당 후보의 통과로 처리하지 않는다.

완료 조건: 한 HTTP 추천 요청으로 `engine.recommendation_run -> rag.retrieval_run ->
rag.retrieval_hit -> evidence.evidence -> candidate/validation_evidence` 관계를 DB에서 추적할 수 있다.

### 6. API 엔드포인트 연결

- `src/routers/session.py`의 각 handler에 `Depends(optional_principal)`과 DB 세션을 주입한다.
- `POST /session/{list_id}/recommend`는 소유권과 입력 완결성을 확인한 후
  `recommendation_service.run_for_revision()`을 호출한다.
- `GET /session/{list_id}/result`는 저장된 결과만 읽는다. 조회할 때 파이프라인이나 RAG를 다시
  실행하지 않는다.
- 오류 매핑을 고정한다.
  - 미인증/잘못된 browser token: 401 또는 정책상 지정값
  - 타 사용자 또는 없는 list: 404
  - required input 누락: 422
  - draft lock 충돌: 409
  - 임베딩/DB 검색 장애: 실행은 failed 또는 후보 unknown, 응답에는 안정적인 오류 코드
- `/dev/run`은 기존 데모로 유지하되 운영 준비 상태를 나타내는 엔드포인트로 사용하지 않는다.

완료 조건: FastAPI TestClient 또는 실제 서버 요청으로 세션 생성부터 결과 조회까지 성공한다.

### 7. 통합 테스트와 회귀 검증

다음 테스트를 추가한다. 테스트는 PGlite/pgvector 또는 명시적 전용 PostgreSQL DB에서 실행하며
각 테스트가 만든 행은 rollback하거나 격리한다.

1. 정상 흐름: guest 세션 생성 → baby 선택 → 필수 조건 저장 → 추천 → 결과 조회.
2. 반환 후보의 설명에 설명서의 `3 kg`, `6개월`, `22 kg` 등 기대 근거와 유효한 locator가 포함됨.
3. 추천 실행 ID가 모든 retrieval run에 연결되고 채택 evidence가 candidate/validation에 연결됨.
4. 근거 없는 질문에는 `no_evidence`가 반환되며 절차가 생성되지 않음.
5. 다른 상품·variant·market의 청크가 섞이지 않음.
6. 타 사용자와 잘못된 browser token이 추천 및 결과를 조회하지 못함.
7. 추천 도중 revision lock version 변경 시 오래된 결과가 게시되지 않음.
8. 자료 철회 또는 발췌 권한 제거 후 기존 결과 조회에서 원문이 다시 노출되지 않음.
9. 임베딩 실패와 DB 검색 실패가 `no_evidence` 또는 성공으로 위장되지 않음.
10. 미검수·조건 누락·충돌 시 안전 통과로 표시되지 않음.
11. 기존 컴퓨터 데모 테스트와 RAG 단위·통합 테스트가 계속 통과함.

검증 명령:

```bash
uv run python -m pytest -q tests/test_rag.py

export DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:55432/postgres?sslmode=disable'
export RAG_TEST_DATABASE_URL="$DATABASE_URL"
uv run python db/migrate.py up
uv run python -m pytest -q
```

Node 18에서 PGlite 테스트 서버를 쓸 때는 현재 알려진 `CustomEvent` 호환 문제를 테스트 도구에
정식으로 해결한다. 매번 수동 `node -e` 우회 명령을 요구하지 않도록 `server.mjs`에 안전한
polyfill을 추가하거나 지원 Node 버전을 명시하고 CI에서 고정한다.

## 구현 순서와 커밋 단위

아래 순서로 작고 검토 가능한 변경을 만든다.

1. API DTO 및 오류 계약
2. principal·소유권 검사와 plan read/write 최소 구현
3. engine recommendation run 및 결과 저장 구현
4. DB 기반 baby 파이프라인과 후보 식별자 계약
5. 후보별 RAG 검증·설명 및 evidence 연결
6. `/session` recommend/result API 연결
7. HTTP+PostgreSQL end-to-end 테스트와 문서 갱신

각 단계에서 관련 테스트를 먼저 또는 함께 추가하고 전체 테스트를 실행한다. 기존 사용자 변경이 있는
작업 트리에서는 관련 없는 파일을 되돌리거나 포맷하지 않는다.

## 완료 정의

다음 조건을 모두 만족해야 완료다.

- 사용자 API에서 baby 추천 요청이 501 없이 완료된다.
- 결과가 실제 PostgreSQL RAG 검색에서 나온 근거를 포함한다.
- 모든 검색에 실제 recommendation run과 정확한 상품·옵션 범위가 있다.
- 검증 및 설명에 사용한 evidence 관계를 DB에서 역추적할 수 있다.
- 권한, 철회, 버전, 적용 조건을 검색과 응답 직전에 검사한다.
- 실패·근거 없음·부분 검증을 사용자 응답에서 구분한다.
- 타 사용자 접근, stale revision, 자료 철회, 장애 경로 테스트가 통과한다.
- 기존 RAG 테스트와 컴퓨터 데모 회귀 테스트가 통과한다.
- `docs/rag_implementation.md`와 API 실행 문서가 실제 서비스 실행법에 맞게 갱신된다.

## 완료 보고 형식

구현 에이전트는 최종 보고에서 다음을 제시한다.

- 연결된 HTTP 흐름과 대표 요청·응답
- 변경한 핵심 파일과 각 파일의 역할
- DB에서 확인한 recommendation/retrieval/evidence 연결
- 실행한 테스트 명령 및 통과 개수
- 사용한 임베딩 공급자·모델 프로필과 실행 환경
- 남은 제한 사항과 운영 전 필수 검증

`local-test` 결과를 운영 임베딩의 의미 검색 품질로 표현하지 않는다. 기능 연결 완료와 운영 검색
품질 검증을 명확히 구분해 보고한다.
