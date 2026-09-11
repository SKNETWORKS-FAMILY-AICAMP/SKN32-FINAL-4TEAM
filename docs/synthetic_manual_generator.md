# 가상제품 사용설명서 생성기

설계 문서의 **규칙 기반 부분 문서 단계**를 구현했다. Python 3.11 이상 표준 라이브러리만 사용하며 API 키나 LLM 호출이 필요 없다. 상품 데이터·검수 프로필에 없는 조작법은 생성하지 않는다.

## 실행

프로젝트 루트에서 실행한다. 출력 폴더는 존재하지 않아야 한다.

```powershell
python scripts/generate_baby_manual.py --input data/synthetic_manuals/stroller_example.json --output generated/synthetic_manuals/stroller_example
```

이 경로에는 이번에 생성한 예시가 있으므로 다시 실행하면 덮어쓰기 방지 오류가 발생한다. 재실행 시 다른 출력 경로를 선택한다.

상품 생성기의 `products[]`, `references[]` 묶음도 입력할 수 있다. 여러 상품이면 반드시 한 건을 지정한다.

```powershell
python scripts/generate_baby_manual.py --input catalog.json --product-id SYN-STROLLER-001 --output generated/synthetic_manuals/another_run --revision R2
```

`--profile profile.json`은 선택 사항이다. 입력 파일에서 한 제품만 읽는 경우 별도 참조를 받지 않으므로, 부품 참조가 있는 제품은 묶음 형태로 제공한다.

## 현재 지원 범위

- 유모차·젖병·기저귀·컵의 부분 문서 템플릿. 유모차는 좌석 모드·신생아 구성 미지원 유형을 지원한다.
- 등록된 월령·체중·키 범위, 혼자 앉기 조건, 체중 초과 중단 조건을 원문 입력 경로와 연결한다. 모르는 조건·모드는 생략하지 않고 오류를 낸다.
- 한 손 접기·자립의 지원/미지원/미확인을 구별한다. 상품의 모든 스펙을 자동으로 사용 지침으로 바꾸지는 않는다.
- 젖병 부품별 관리법은 등록된 방법까지만 설명하며 소독 온도·시간을 발명하지 않는다.
- 검수된 가상 절차 프로필을 통해 설치·준비·사용·관리·문제 해결·보관 절을 추가할 수 있다.
- 입력·참조·조건 검증, 사실 원장, 블록별 근거 위치, 파일 해시, 생성 이력, 덮어쓰기 방지를 구현했다.

**모든 출력은 현재 `coverage_status=partial`이다.** 일부 프로필 절이 완성되어도 모델 전체의 안전·경고·구성품 계약이 완성되었다고 판정하지 않는다. 나머지 19개 품목, 새로운 조건 표현, 완전 설명서 판정, LLM 표현 변형, PDF, RAG 인제션 및 평가 정답 생성은 후속 구현 범위다. 입력에 없는 기능을 지원한다고 주장하는 대신 명시적으로 실패하거나 누락 범위를 표시한다.

## 출력 묶음

| 파일 | 내용 |
|---|---|
| `manual.md` | 사람이 읽는 사용설명서 한 건 |
| `facts.jsonl` | 사실 ID·값·단위·조건·원본 경로 |
| `mapping.json` | 문서·상품·버전·완성도·누락 절 및 블록→사실 매핑 |
| `product.snapshot.json` | 사용한 상품 레코드 |
| `references.snapshot.json` | 부품·호환 참조 입력 |
| `profile.snapshot.json` | 절차 프로필 또는 null |
| `validation.json` | 생성 시 데이터 일관성 검사 결과 |
| `manifest.json` | 버전·입력 해시·출력 파일 해시·생성 설정 |

Markdown 위치는 **Unicode 문자 기준 0부터 시작, 끝 제외**이며 바이트 오프셋이 아니다. `line_start`는 1부터 시작한다. 페이지 번호는 만들지 않는다. 모든 파일은 UTF-8, LF이며 원본 파일이 바뀌면 인용 위치를 다시 생성해야 한다.

검증 보고서의 passed는 데이터 일관성 검사 통과를 뜻한다. 실제 제품 안전 검증이나 모든 필드의 품목별 법규 검증은 아니다. `facts.jsonl`과 입력·프로필 스냅샷은 생성·검수용으로 보관하고 검색 문서에는 `manual.md`만 사용한다. 평가 정답을 같은 검색 폴더에 넣지 않는다.

## 절차 프로필 계약

프로필은 상품 ID뿐 아니라 정규화한 상품 전체 SHA-256에 묶는다. `canonical(product)`와 `digest()` 함수로 해시를 계산한다. 상품 변경 시 재검수가 필요하다.

필수 필드:

- `profile_id`, `version`: 영문·숫자·밑줄·하이픈 식별자.
- `is_synthetic=true`, `review_status="reviewed"`.
- `category_id`, `product_id`, `product_sha256`.
- `procedures[]`: `section`, `states`, `initial_state`, `terminal_state`, `steps`.
- 각 단계: `requires_state`, `resulting_state`, `required_parts`, `action`, `confirmation`, `on_failure`, `warnings`.

한 절에는 하나의 선형 절차를 연결한다. 지원 절은 S03/S04/S05/S08/S09/S10이며, 순환이나 분기 절차는 지원하지 않는다. `required_parts`의 모든 ID는 입력 참조 배열에 존재해야 한다. 모든 단계가 초기 상태에서 종료 상태까지 연결되는지 검사한다. 경고 문장은 해당 단계와 함께 보존한다.

프로필의 자연어는 **사람이 검수한 입력 사실**로 취급한다. `review_status`라는 문자열만으로 사람이 실제 검수했는지 증명할 수는 없다. 프로필 자체의 문장 의미·실제 기구 적합성은 생성기가 자동 인증하지 않는다. 코드가 생성한 문장을 LLM으로 재검증한 것처럼 표시하지 않는다.

## 예시 레코드 출처

`data/synthetic_manuals/stroller_example.json`은 기존 `유아용품_가상제품_데이터생성용_스펙조사_2026-09-10.md`의 JSON 코드 블록을 그대로 별도 파일로 복원한 것이다. 누락된 스펙 사전 없이 이 레코드만으로 테스트할 수 있다. 원본에 접기 순서·브레이크 구조·관리 지침이 없어 출력은 부분 설명서다.

## 테스트

```powershell
python -m unittest discover -s tests -p test_generate_baby_manual.py -v
```

재현성·원본 불변성, 한 건 선택, 사용 상한과 중단 조건 충돌, unknown/false 구별, 미등록 조건·참조 거부, 실제 상품 거부, 부품별 관리 분리, 절차 상태·제품 해시, 근거 위치·변조 탐지, 한 문서 출력·덮어쓰기 방지를 검증한다. 테스트가 만드는 파일은 임시 폴더에서 제거되며 최종 예시 설명서는 한 건만 남는다.
