# P3 develop 전환 결과 검토 — 2026-09-14

## 판정

**P3 partial 유지. D3-01은 부분 충족, D3-02는 외부 backend 미선택/미연결로 blocked다. P4 순수 계산 및 P5의 미설정·실패 응답 구현은 진행할 수 있지만 검증된 유아 추천의 통합 완료는 승인할 수 없다.**

대상: HEAD `110f6ca` + 현재 P3 미커밋 변경, [P3 최신 v3 보고서](P3.md), [ACTIVE DB CONTRACT](../P3_verification_rag.md). 보고서의 테스트 결과를 재사용하고 코드·테스트를 정적으로 대조했다. 이번 검토에서 테스트·적재·DB 설치를 다시 실행하지 않았다. 아래 결함은 새 동적 재현 결과가 아니다.

## 인정하는 성과

SearchProvider Protocol과 LocalFileSearchProvider는 실제 파일 게시·검색·조회·철회를 구현한다. assets의 분리된 설명서/버전/적용 관계와 evidence.source를 사용하며 기존 rag SQL 저장 경로를 전환했다. 미설정 provider는 명시적 error를 반환한다.

보고서의 관련61건 및 설명서21/21 실적은 로컬 파일 provider와 synthetic 설명서의 해당 범위에서 인정한다. 다른 run 근거·미존재 근거·revoked revision 거부 및 파일 공개/스캔/저장 상태 검사의 구현과 테스트를 확인했다. 이 결과를 실제 외부 검색 backend나 실제 상품의 안전 검증 완료로 확대하지 않는다.

## D3-01 승인 전 수정할 문제

### R1 — 같은 run의 다른 상품·requirement 근거를 연결할 수 있음

`src/repo/engine_repo.py`의 persist_candidate_check는 candidate가 run에 속하는지만 검사한다. candidate.requirement_id와 check.requirement_id/issue.target.requirement_id, run.revision_id의 일치는 확인하지 않는다. `_validated_evidence_ref`도 evidence의 run ID와 revision 게시 상태만 확인하고 candidate의 product/variant에 해당 자료가 적용되는지 검사하지 않는다.

한 run에는 여러 상품 후보가 있으므로 run 일치만으로 상품 근거 범위를 보장하지 못한다. 같은 run에서 상품 A의 설명서를 상품 B의 검증 근거로 넘겨도 이를 거부하는 코드가 없다. 기존 cross-run 테스트는 이 문제의 증거가 아니다.

수정: candidate→requirement→revision과 run→revision을 비교하고 check/issue target도 같은 requirement로 제한한다. 근거의 material_revision에 대해 실제 후보 product/variant와 market/corpus 등의 적용 조건을 확인한다. 같은 run·다른 상품/옵션/requirement 사례와 실패 후 부분 validation/JSON 행이 남지 않는 사례를 검증한다. P0 공통 저장소 경계와 함께 수정하되 P3 pass를 먼저 선언하지 않는다.

### R2 — 공개 근거 조회에서 현재 적용 범위·해시를 재검사하지 않음

`src/repo/rag_repo.py`의 resolve_public_evidence는 evidence.status, facts의 run ID 및 MaterialRepo.is_currently_published만 확인한 후 citation_snapshot.text를 돌려준다. is_currently_published는 공개 권한·스캔·저장·게시 상태를 확인하지만 material_applicability.verified/상품·옵션/market/corpus 및 snapshot 해시와 현재 파일 해시 일치는 검사하지 않는다.

따라서 검색 후 자료의 상품 적용 승인을 해제하거나 파일 해시가 달라져도, 게시 상태만 유지되면 과거 문장이 available=true로 반환될 수 있다. provider.resolve/revoke 상태도 조회 경로에서 사용하지 않으므로 외부 철회와 DB 철회를 연결할 정책이 필요하다. 또한 scope와 facts 모두 run ID가 누락되면 str(None)==str(None) 비교를 통과한다.

수정: 신뢰할 수 있는 현재 run/candidate 범위를 필수로 전달하고 누락 scope는 거부한다. 현재 적용 승인·상품/옵션·해시를 다시 확인해 불일치하면 원문을 가리고 이유를 남긴다. 외부 hit 철회가 DB에 반영되는 절차 또는 조회 시 resolve 검사를 구현한다. 기존 게시 revision 철회 테스트 외에 적용 승인 해제/해시 변경/외부 hit 철회/누락 scope 검증이 필요하다.

### R3 — provider 응답의 상품·corpus와 원문 무결성 검증 부족

`src/rag/service.py`는 응답 hit의 material_revision_id, 게시 상태, file_sha256 문자열 일치만 검사한다. ProviderHit의 product_id/variant_id/corpus는 요청·DB 범위와 대조하지 않으며 verified와 text/locator를 그대로 사용한다. `LocalFileSearchProvider`가 정상 응답만 주는 기존 테스트로는 이 경계가 검증되지 않는다.

현재 provider는 저장된 content_hash를 실제 chunk.text와 비교하지 않는다. 문서 해시 문자열만 동일하게 남긴 채 text/locator를 바꾼 hit도 서비스에서 받아들일 수 있다. 외부 provider 연결 전에 경계를 강화해야 한다.

수정: 응답 product/variant/corpus와 provider identity를 요청 및 DB 메타데이터와 대조한다. 신뢰하는 원본/청크 hash와 locator 범위로 인용 텍스트 일치를 검증하고 verified 여부는 서버의 검토 정보로 판단한다. 동일 revision/hash 문자열을 가진 잘못된 상품·corpus·텍스트 hit를 공급하는 경계 테스트를 추가한다. 정상적인 로컬 검색과 별개로 잘못된 backend 응답을 거절하는 증거를 남긴다.

### R4 — JSON 계약 검사와 저장된 issue 구조가 불충분함

EvidenceRef의 UUID/hash는 단순 str이고 locator는 제한 없는 dict다. `_validated_evidence_ref`는 해시 누락을 빈 문자열, 위치 누락을 빈 객체로 대체하여 모델 검증을 통과시킬 수 있다. provider/external_hit_id도 선택 값이다. “malformed refs 거부” 주장은 현재 형식 검증보다 넓다.

persist_candidate_check는 ValidationIssue 모델로 저장 payload를 만들지 않고 link_validation_target을 통해 target/evidence_refs만 issues 배열에 추가한다. 공통 계약이 요구한 개별 issue의 schema_version/rule/status/reason 등을 포함한 형식과 다르다. 재시도 시 validation/issue 중복 처리도 검증되지 않았다.

수정: 최소 필드·UUID·해시·위치·provider 식별자를 검증하고 전체 typed issue를 저장한다. 공통 serializer로 직접 link 경로도 통일한다. 누락/잘못된 형식/중복 및 저장·재조회 왕복 사례를 검증한다.

## 보고서 경계·정확성

- D3-02를 blocked로 남긴 것은 적절하다. 로컬 파일 provider는 실구현이지만 승인된 외부 검색/벡터 backend 통합을 증명하지 않는다. 다음 구현이 반드시 상용 SaaS일 필요는 없으나 선택된 별도 backend에서 publish/search/resolve/revoke·재시작 복원을 증명해야 한다.
- 유아 HTTP501은 현재 추천 진입부에 있으나 “P2 저장소가 아직 node 기반으로 전환되지 않아 발생”이라는 설명은 최신 P2 코드와 다르다. P2 저장 경로는 전환됐고 추가 결함은 별도 검토에 있다. 501 제거 및 구 PlanRepo 호출 정리는 P5 연결 과제로 기록해야 한다. dead code 안 RagService 생성자 변경만으로 전체 연결이 올바르다고 판단하지 않는다.
- --ignore로 유아 HTTP 파일을 뺀268건 통과는 제한된 실행 범위다. 포함 실행에서 발생한 인증3건의 추가 실패는 별도 원인 확인이 필요하며, 제외 실행 성공만으로 “P3와 무관한 기존 pool 문제”를 확정할 수 없다. 비교 실행 근거·원인 분석이 없으면 원인 미확정으로 기록한다.
- 과거 P1 exact 유실 문제를 현재 미해결로 그대로 이월하지 않는다. 현재 P1 검토는 exact 보존을 인정했고 활성 규칙/보유량 입력 문제를 지적했다.

## 다음 단계 진행 조건

| 단계 | 판단 |
|---|---|
| P4 | pass/fail/unknown DTO에 대한 순수 계산 및 unknown 미선택 규칙 구현 가능. P2 보유량 문제와 위 근거 범위 문제 해소 전 실제 DB 입력 기반 완료 승인 보류 |
| P5 | 202 실행 연결·미설정/오류 종료·결과 표시 준비 가능. 실제 검증 포함 정상 추천 완료는 D3-01 보완 및 D3-02와 선행 P0/P1/P2 게이트 필요 |
| P7/P9 | 확정 안전 검증·운영 준비 완료 승인 보류. 외부 검색 장애·철회·재시작 복원까지 최종 검증 필요 |

P0/P2 미해결 항목을 자동 해소로 간주하지 않는다. 이번 P3에서 일부 근거 검증을 추가했더라도 전체 P0 재승인은 별도 대조가 필요하다. 우선 R1/R2를 공통 저장·공개 경계에서 수정하고 R3/R4를 보완한다. 기존 정상 테스트는 재사용하며 새 경계 회귀만 추가 검증한다.
