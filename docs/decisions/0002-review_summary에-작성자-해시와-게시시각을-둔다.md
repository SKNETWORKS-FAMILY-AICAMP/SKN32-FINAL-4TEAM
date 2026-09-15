# 0002. `evidence.review_summary` 에 `author_ref`(솔트 해시)·`review_posted_at` 을 둔다

- 날짜: 2026-09-11
- 상태: 채택
- 관련: `db/migrations/0010_review_summary_relation_axis.sql` · 명세서 §42 ·
  `src/workers/relation_axis.py`

## 맥락

관계·행동 축은 본문을 보지 않는 대신 **누가 · 언제** 를 본다. 리뷰 탐지 사전 조사가 다섯 축
중 유일하게 "쓸 만하다" 로 남긴 축이고, 이 저장소에서 오늘 실데이터(Amazon'23 Baby 6.0M건)로
처음 돌아갔다. 그런데 산출한 관측 사실을 컬럼에 대응시키면 전부 둘 중 하나를 요구한다.

| 관측 사실 | 필요한 것 |
| --- | --- |
| 리뷰어 N명이 다른 상품에서도 함께 나타남 · 연결 상품 · 군집 · 1건 계정 비율 · 다작 비율 | 작성자 |
| 7일 안에 몰린 리뷰 비율 | 게시 시각 |
| 계정 활동 기간 · 리뷰 간 간격 | 둘 다 |

`evidence.review_summary`(외부 리뷰의 온라인 경로)에는 둘 다 없다. `collected_at` 은 우리가
긁은 시각이라 대신 쓰면 한 번에 수집한 리뷰가 전부 "같은 날 몰림" 으로 보인다 — 없는 것보다
나쁘다. 이 상태로는 축이 외부 데이터셋(`dataset.*`) 위에서만 돌고, 서비스가 실제로 추천하는
제품의 화면에는 영원히 붙지 않는다.

**소급 불가다.** 수집기가 작성자·게시시각을 버리면 나중에 되찾을 수 없다. 컬럼은 `ALTER TABLE`
한 줄이라 비워 두는 비용이 0 인데, 없으면 축 하나가 제품에서 사라진다.

## 검토한 대안

| 대안 | 판단 |
| --- | --- |
| **`review_summary` 에 두 컬럼 추가 (NULL 허용)** | **채택** |
| 별도 테이블 `evidence.review_author_link(summary_id, author_ref, posted_at)` | 같은 효과, 조인 하나. 팀 테이블을 건드리지 않는 장점. 팀이 원 테이블 수정에 반대할 때의 대안으로 남긴다 |
| `dataset.review_sample` 에만 `author_ref` 추가 | 기각. 축이 오프라인 실험·라벨링에서만 돈다 — "관계 축 우선순위를 올린다" 와 모순 |
| 추가하지 않음 | 기각. 관계 축은 외부 데이터 카드로 끝난다 |
| 원 작성자 ID 를 그대로 저장 | 기각. 필요한 것은 "같은 계정인가" 뿐이다. 해시로 충분하고, 원식별자는 원문 미저장 정책의 정신에 어긋난다 |

## 결정

1. `evidence.review_summary` 에 `author_ref text NULL`·`review_posted_at timestamptz NULL` 을 추가한다
   (`0010_review_summary_relation_axis.sql`). 부분 인덱스 둘
2. `author_ref` 는 **소스별 솔트 해시** — `hash(salt[source_id] || external_author_id)`. 원식별자는
   저장하지 않고 역산하지 않는다. 소스가 다르면 같은 사람이라도 다른 값이다(소스 간 연결은
   이 컬럼의 목적이 아니다)
3. 소스가 제공하지 않으면 **NULL 로 둔다.** 기본값·`collected_at` 으로 채우지 않는다. NULL 인 행은
   관계 축 계산에서 "정의되지 않음" 이다. `review_posted_at` 은 이미 있는
   `dataset.review_sample.review_posted_at` 과 같은 이름·같은 의미로 맞췄다
4. `origin='first_party'` 행은 `community.review.author_user_id` 의 솔트 해시와
   `community.review_revision.published_at` 으로 채운다 — 축이 origin 을 가르지 않게
5. 이 축의 산출물로 `cleaning_status` 를 바꾸지 않는다 — 상품 단위 신호로 개별 리뷰를 제외하지
   않는다 (ADR-0001)
6. 수집기는 작성자 식별자와 게시 시각을 **처음부터** 잡는다

## 대가

- 팀 운영 테이블을 건드린다. upstream 합의가 필요하다. 마이그레이션 번호는 처음 `0006_rag_active_profile`
  뒤인 `0007` 로 잡았으나, upstream 이 `0007~0009` 를 먼저 쓰는 바람에 **2026-09-12 에 `0010` 으로 다시
  밀었다**(아래 대가의 "번호 재조정" 이 그대로 현실화한 것이다). 번호를 우리가 정할 수 없는 것이 이
  결정의 상시 비용이다
- 해시라도 한 사람의 리뷰들을 잇는 **가명 식별자**다. 개인정보 처리 관점의 검토(수집 대상 소스의
  약관, 보관 기간)가 필요했고 **2026-09-11 팀 확인을 받았다.** 이 ADR 은 그 검토를 대신하지 않는다
- upstream 반영은 **나중에 한 번에** 올리기로 했다(2026-09-11 합의). 그동안 팀 테이블이 갈라지는
  영향(같은 테이블을 고치는 다른 브랜치와의 충돌, 마이그레이션 번호 재조정)은 감수한다
- 계정당 리뷰 중앙값이 1 인 데이터(Amazon'23 Baby: 3건+ 계정 14.7%, 그 계정들이 리뷰의 43%)에서는
  계정 단위 특징이 소수에서만 정의된다. 컬럼을 넣어도 상품 단위 특징(몰림·공유 리뷰어)이 주력이고,
  계정 단위는 "정의된 비율" 을 함께 낸다
- 수집기 구현이 한 단계 늘어난다 — 작성자 필드를 노출하지 않는 소스가 있으면 그 소스는 이 축에서
  빠진다

## 추기 — 2026-09-13

upstream 의 DB 축소(58→35, `docs/db/db_schema_reduction_proposal_2026-09-12.md`)가 이 ADR 이 기대던
앵커 둘을 없앤다. **결정은 유지된다** — `evidence.review_summary` 는 축소안에서 "병합 금지" 로 유지
확정돼 컬럼이 붙을 집은 살아 있다. 다만 위 결정의 근거 문장 둘이 가리킬 곳을 잃는다:

- **결정 3** 은 `review_posted_at` 의 의미를 `dataset.review_sample.review_posted_at` 과 "같은 이름·같은
  의미" 로 맞췄는데, `dataset` 스키마 4개가 전부 삭제(로컬 파일 전환)된다. **의미 정의를 이 ADR 이
  직접 지게 된다** — "리뷰가 원 소스에 게시된 시각. 우리가 수집한 시각(`collected_at`)이 아니다."
- **결정 4** 의 `community.review_revision.published_at` 은 `review` + `review_revision` 병합으로
  테이블이 사라진다. `origin='first_party'` 채우는 규칙을 병합 테이블 기준으로 다시 써야 한다

둘 다 컬럼 요구는 아니다. 이 ADR 이 요구하는 테이블 변경은 여전히 `review_summary` 두 컬럼 + 부분
인덱스 둘 하나뿐이다.
