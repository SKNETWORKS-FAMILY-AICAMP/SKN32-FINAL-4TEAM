-- 0010_review_summary_relation_axis.sql — 관계·행동 축이 온라인 경로에서 서게 하는 두 컬럼
--
-- 관계·행동 축(리뷰어–상품 그래프: 7일 몰림 · 공유 리뷰어 · 계정 신규성 · 리뷰 간 간격)은
-- 본문을 보지 않는 대신 **누가 · 언제** 를 본다. 그런데 evidence.review_summary 에는
-- 둘 다 없다 — collected_at 은 우리가 수집한 시각이지 리뷰가 게시된 시각이 아니고,
-- 작성자 식별자는 아예 없다. 이 상태로는 오프라인(dataset.*)에서 계산한 관측 사실을
-- 온라인 근거 카드에 붙일 수는 있어도, 온라인 요약만으로는 축이 다시 계산되지 않는다.
--
-- 원문 미저장 정책(명세서 "리뷰 원문 보관 정책")과 충돌하지 않는다:
--   · author_ref 는 외부 작성자 식별자의 **해시**(소스별 솔트) — 원문도 개인정보도 아니며
--     같은 계정이 다른 상품에 나타났는지만 잇는다. 역산 불가.
--   · review_posted_at 은 메타데이터다.
--
-- 둘 다 NULL 허용. 소스가 작성자·게시시각을 주지 않으면 비워 두고, 그 상품의 관계 축은
-- "정의되지 않음" 으로 남는다(0 이나 기본값으로 채우지 않는다).
-- review_posted_at 은 dataset.review_sample.review_posted_at 과 같은 이름·같은 의미다.
-- origin='first_party' 행은 community.review.author_user_id 의 솔트 해시와
-- community.review_revision.published_at 으로 채운다 (명세서 §42 규칙).

ALTER TABLE evidence.review_summary
  ADD COLUMN author_ref        text,
  ADD COLUMN review_posted_at  timestamptz;

COMMENT ON COLUMN evidence.review_summary.author_ref IS
  '외부 작성자 식별자의 소스별 솔트 해시. 관계·행동 축(공유 리뷰어·신규성·간격)용. 원식별자는 저장하지 않는다.';
COMMENT ON COLUMN evidence.review_summary.review_posted_at IS
  '리뷰가 원 소스에 게시된 시각(UTC). collected_at(우리 수집 시각)과 다르다. 7일 몰림·간격 계산용.';

-- 관계 축 질의: (같은 작성자의 다른 상품) · (상품별 시간 창)
CREATE INDEX review_summary_author_ref_idx
  ON evidence.review_summary (author_ref)
  WHERE author_ref IS NOT NULL;
CREATE INDEX review_summary_subject_posted_idx
  ON evidence.review_summary (subject_id, review_posted_at)
  WHERE review_posted_at IS NOT NULL;
