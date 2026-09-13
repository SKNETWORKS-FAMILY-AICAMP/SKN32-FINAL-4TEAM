# 설명서 RAG 구현 및 테스트

## 구현 범위

가상제품 생성기의 `manual.md`를 읽어 기존 `assets → rag → evidence` 테이블에
게시하고, PostgreSQL pgvector와 키워드 검색으로 근거를 반환한다. 대상 예시는
`generated/synthetic_manuals/stroller_example`의 부분 유모차 설명서다.

- 검색 콘텐츠는 `manual.md`뿐이다. `mapping.json`은 식별자와 무결성 확인에만 사용한다.
  `facts.jsonl`, 제품 스냅샷, 평가 정답은 검색하거나 임베딩하지 않는다.
- 절 단위 청크 5개. 월령·체중·발달 조건과 경고를 함께 유지한다.
  원문 SHA-256, 문자 범위, 1부터 시작하는 줄 번호, 절·블록 ID를 보존한다.
- 관리자가 CLI로 가상 자료를 등록한다. 임베딩 전체 성공 후 게시 트랜잭션을 실행한다.
  실패 시 기존 게시 버전은 유지되고, 같은 문서·버전·모델·검수 상태는 중복 적재되지 않는다.
- 실제 검색 SQL은 공개 여부, RAG·발췌 허용, 파일 상태, 현재 게시 버전, 활성 추출 작업,
  상품·옵션·시장·언어·도메인·적용 조건·가상/실제 코퍼스·모델 프로필을 검사한다.
  인용 생성 직전에 다시 검사하며, 과거 인용 조회도 `resolve_evidence`를 통해 확인한다.
- 관련도는 정확 코사인 검색 + 한국어 문자 bigram/모델명 키워드 검색을 RRF로 결합한다.
  초기 후보 20개, 반환 5개, 벡터 관련도 하한 0.20은 **평가 시작값**이며 운영 보정이 필요하다.
- 검색 실행·검색 결과·채택 인용을 저장한다. `success`, `no_evidence`, `error`를 구분한다.
  오류가 빈 근거나 목 결과로 바뀌지 않는다.
- 답변은 인용 가능한 설명서 발췌다. 문서의 지시문을 실행하거나 도구 호출에 사용하지 않는다.
  기능 지원을 조작 순서로 확장하지 않으며, 미기재 관리·조립·소독 방법은 답하지 않는다.
- `verify_baby_manual`은 검색된 **검수 완료** 문장에서 정해진 좌석 조건만 규칙으로 확인한다.
  6개월 이상 AND 22kg 이하 AND 혼자 앉기 조건을 모두 검사한다. 미입력·상충·미검수는 unknown.
  부분 설명서에서 조건이 통과해도 전체 안전 검증 상태는 partial이며 신뢰도 점수를 만들지 않는다.
- `explain_manual`은 실제 RAG 설명 경로다. 기존 PC 데모 시나리오의 목 파이프라인은 유지한다.

## 환경

Python 3.11, PostgreSQL + pgvector. `uv sync --locked`로 의존성을 설치한다.
설정은 프로세스 환경변수로 전달한다. `.env.example`은 예시이며 CLI가 `.env`를 자동 로드하지 않는다.

Bedrock 경로는 boto3 기본 자격증명 체인과 `AWS_REGION` 또는 `LLM_REGION`을 사용한다.
`EMBEDDING_MODEL` 기본값은 `amazon.titan-embed-text-v2:0`, 차원은 기존 DDL과 같은 1024다.
연결 5초·읽기 20초, SDK 시도는 최대 2회다. 실제 응답의 차원·유한수·영벡터 여부를 검증한다.
[Titan 요청 계약](https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-titan-embed-text.html)

`--provider local-test`는 네트워크 없는 **어휘 해시 벡터**다. 의미 임베딩 모델이 아니며
Bedrock 장애 시 자동으로 선택되지 않는다. 실제 코퍼스 조회도 금지한다.
프로필이 달라지면 같은 차원이어도 검색할 수 없다. 활성 모델 전환은 재임베딩 및 명시적 전환 작업이 필요하다.

## 재현: 임시 PostgreSQL 테스트

Docker가 없는 환경을 위해 PGlite(PostgreSQL WASM) + pgvector 테스트 서버를 제공한다.
실제 psycopg 프로토콜과 스키마·FK·pgvector SQL을 실행하지만, 운영 PostgreSQL의 부하·동시성·복제 검증은 아니다.
서버는 루프백 `127.0.0.1:55432`에서만 열리며 종료하면 DB가 사라진다.
[PGlite 설명](https://pglite.dev/docs/about), [소켓 서버](https://pglite.dev/docs/pglite-socket)

첫 번째 PowerShell:

```powershell
npm ci --prefix tests/rag_pg
node tests/rag_pg/server.mjs
```

두 번째 PowerShell:

```powershell
$env:PYTHONUTF8='1'
$env:DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:55432/postgres?sslmode=disable'
$env:RAG_TEST_DATABASE_URL=$env:DATABASE_URL
uv run python db/migrate.py up
uv run python -m pytest -q
uv run python scripts/rag_manual.py ingest --provider local-test
uv run python scripts/rag_manual.py evaluate --provider local-test --new-test-run
uv run python scripts/rag_manual.py query --provider local-test --new-test-run --query '바구니 최대 하중은?'
```

PostgreSQL 통합 테스트는 `RAG_TEST_DATABASE_URL`이 있을 때만 실행한다. 전용 테스트 DB를 지정한다.
각 테스트가 만든 DB 행은 rollback한다. 파일 복사본은 테스트 임시 폴더에 저장한다.
CLI가 게시한 로컬 원본 복사본은 `.rag-files/`(git 제외)에 보존한다.
이 경로는 관리자용 로컬 객체 저장소이며 범용 파일 업로드 API가 아니다.

`--new-test-run`은 가상 평가용 대화·계획·추천 실행을 명시적으로 생성한다.
실제 소비처는 접근 권한을 확인한 추천 실행 ID를 `SearchRequest.recommendation_run_id`에 전달해야 한다.
서비스 함수 자체가 사용자 인증을 대신하지 않으므로 인증 없이 HTTP로 직접 노출하지 않는다.

## 실제 Bedrock 실행

별도 개발 DB에 마이그레이션을 적용하고 AWS 프로필·리전을 설정한 뒤:

```powershell
$env:AWS_PROFILE='configured-profile'
$env:AWS_REGION='configured-region'
# DATABASE_URL은 개발 DB. RAG_TEST_DATABASE_URL이 남아 있으면 CLI가 그 DB를 우선 사용한다.
uv run python scripts/rag_manual.py ingest --provider bedrock
uv run python scripts/rag_manual.py evaluate --provider bedrock --new-test-run --report generated/rag/stroller_bedrock_evaluation.json
```

로컬 테스트 모델이 활성인 DB에 Bedrock을 바로 게시하면 의도적으로 실패한다.
테스트 모델이 없는 별도 DB를 사용하거나, 검토된 프로필 교체 작업을 먼저 수행한다.
`--reviewed`는 관리자의 문서 검수 완료 명시다. 생성기의 validation 결과로 자동 설정하지 않는다.
가상 설명서의 실제 안전 인증을 의미하지 않는다.

## 검증 결과 및 한계

실행 결과는 `generated/rag/stroller_evaluation.json`과 `generated/rag/test_results.xml`에 저장했다.
전체 58개 테스트와 3개 subtest가 통과했다. 실행 DB는 PostgreSQL 18.3 (PGlite 0.5.8) / pgvector 0.8.1이다.
21개 설명서 질의는 12개 기재 사실·9개 미기재/적용 범위 밖 질문으로 구성했다.
경계값, 상충, 해시 변조, 정답 원장 비사용, 권한·철회·버전, SQL·임베딩 장애, 인용 추적을 별도로 테스트한다.

현재 확인한 것은 단일 가상 부분 설명서에서의 동작과 SQL 통합이다. 한국어 자유 질의 전반의 검색 품질이나
실제 제품 안전성을 보장하지 않는다. Bedrock 자격증명·리전이 없는 환경에서는 실모델 호출을 수행하지 않으며,
SDK 요청 계약 테스트를 실제 모델 평가로 보고하지 않는다.

이번 범위에 자동 웹 수집, PDF/OCR·이미지 파싱, 비동기 업로드 큐, 모델 자동 전환,
S3 원본 제공, 전체 추천 UI 연결은 포함하지 않았다. 초기 적재는 동기 관리자 CLI를 사용한다.
기존 큐 진입점은 지원하지 않는 작업을 ready로 표시하지 않고 명시적으로 실패 처리한다.
