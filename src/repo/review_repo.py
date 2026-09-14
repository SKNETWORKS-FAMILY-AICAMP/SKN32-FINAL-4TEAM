"""리뷰 저장소 — community.review/review_revision + evidence.review_subject/summary/aggregate(_member).

P0 v3: review/review_revision, pc_build/pc_build_version 은 community.review 하나로 병합됐고
(record_type 'review'|'build'), pc_build_component 는 community.review_component 로 이름이 바뀌었다.

리뷰 진위 탐지·오프라인 클렌징·review_summary 산출 로직은 리뷰 담당 팀원.
이 repo 는 그 산출물을 읽고([3-B]/[3-C]가 소비), 서비스 작성 리뷰(A7)를 저장한다.
외부 리뷰 원문 미저장(§15). 전체 PC 리뷰는 published + assembled_self_reported 구성에 연결(C11).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from src.db.base import Repo
from psycopg.types.json import Jsonb


class ReviewSubjectRepo(Repo):
    def get_or_create(self, *, product_id: UUID | None = None, variant_id: UUID | None = None,
                      offer_id: UUID | None = None, build_version_id: UUID | None = None) -> UUID:
        """정확히 하나만 non-null (CHECK). 각 FK 부분 UNIQUE."""
        refs = {"product_id": product_id, "variant_id": variant_id, "offer_id": offer_id, "build_version_id": build_version_id}
        chosen = [(key, value) for key, value in refs.items() if value is not None]
        if len(chosen) != 1:
            raise ValueError("exactly one review subject reference is required")
        key, value = chosen[0]
        row = self._one(f"SELECT id FROM evidence.review_subject WHERE {key}=%s", (value,))
        if row is None:
            row = self._one(f"INSERT INTO evidence.review_subject ({key}) VALUES (%s) RETURNING id", (value,))
        return row["id"]

    def resolve_by_key(self, product_key: str, variant_key: str | None = None) -> UUID | None:
        """P8 파일 기반 분석 적재용 — `catalog.product.model`/`product_variant.variant_key`로
        찾는다. 카탈로그에 없으면 None(파일이 존재하지 않는 상품을 가리키는 것과 다르지 않다 —
        가짜 subject를 만들지 않는다)."""
        if variant_key:
            row = self._one(
                """SELECT v.id AS variant_id FROM catalog.product_variant v JOIN catalog.product p ON p.id=v.product_id
                   WHERE p.model=%s AND v.variant_key=%s""", (product_key, variant_key))
            if row is None:
                return None
            return self.get_or_create(variant_id=row["variant_id"])
        row = self._one("SELECT id FROM catalog.product WHERE model=%s", (product_key,))
        if row is None:
            return None
        return self.get_or_create(product_id=row["id"])


class ReviewRepo(Repo):
    # ── 서비스 작성 리뷰 (A7) ──
    def create(self, author_user_id: UUID, subject_id: UUID) -> UUID:
        return self._one("""INSERT INTO community.review(author_user_id,subject_id) VALUES(%s,%s)
          ON CONFLICT(author_user_id,subject_id) DO UPDATE SET updated_at=now() RETURNING id""", (author_user_id,subject_id))["id"]

    def add_revision(self, review_id: UUID, *, domain_version_id: UUID, rating: int,
                     title: str, body: str, axis_scores: dict, usage_context: dict) -> UUID:
        number = self._one("SELECT COALESCE(MAX(revision_no),0)+1 AS n FROM community.review_revision WHERE review_id=%s", (review_id,))["n"]
        row = self._one("""INSERT INTO community.review_revision(review_id,revision_no,domain_version_id,rating,title,body,axis_scores,usage_context)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""", (review_id,number,domain_version_id,rating,title,body,Jsonb(axis_scores),Jsonb(usage_context)))
        self._exec("UPDATE community.review SET status='draft',updated_at=now() WHERE id=%s", (review_id,))
        self._exec("""UPDATE evidence.review_aggregate a SET status='stale',updated_at=now() FROM community.review r
          WHERE r.id=%s AND a.subject_id=r.subject_id AND a.status='ready'""", (review_id,))
        return row["id"]

    def publish(self, review_id: UUID, revision_id: UUID) -> None:
        """current_revision 전환 + 관련 요약·집계 stale(C12, §8.4)."""
        self._exec("UPDATE community.review_revision SET moderation_status='approved',published_at=COALESCE(published_at,now()),updated_at=now() WHERE id=%s AND review_id=%s", (revision_id,review_id))
        self._exec("UPDATE community.review SET current_revision_id=%s,status='published',updated_at=now() WHERE id=%s", (revision_id,review_id))

    def owned(self, review_id: UUID, user_id: UUID) -> dict | None:
        return self._one("SELECT * FROM community.review WHERE id=%s AND author_user_id=%s", (review_id,user_id))

    def baby_domain_version(self) -> UUID | None:
        row = self._one("SELECT dv.id FROM config.domain_version dv JOIN config.domain d ON d.id=dv.domain_id WHERE d.code='baby' ORDER BY dv.version_no DESC LIMIT 1")
        return None if row is None else row["id"]

    # ── 집계·요약 읽기 ([3-B] 리뷰축 / [3-C] 리뷰 진위 / S5, P8 파일 기반 분석) ──
    def get_summary(self, subject_id: UUID, *, domain_version_id: UUID | None = None,
                    source_scope: str = "combined") -> dict | None:
        """검수 승인된(파일 임포트가 만든) 최신 `ready` review_aggregate 한 행.

        domain_version_id를 주면 그 버전으로 좁힌다(유아/PC 집계 분리, schema-v1
        "domain_version별 분리"). status='ready'만 본다 — stale/revoked는 공개하지 않는다
        (P8 IMPLEMENTATION3 "현재 승인된 revision만 공개·집계")."""
        params: list = [subject_id, source_scope]
        where_domain = ""
        if domain_version_id is not None:
            where_domain = "AND domain_version_id=%s"
            params.append(domain_version_id)
        return self._one(f"""SELECT * FROM evidence.review_aggregate
          WHERE subject_id=%s AND source_scope=%s {where_domain} AND status='ready'
          ORDER BY window_end DESC LIMIT 1""", tuple(params))

    def top_summaries(self, aggregate: dict, limit: int = 3) -> list[dict]:
        """aggregate.ratings.summary_texts (import CLI가 쓴 대표 요약 문장)에서 상위 N개."""
        texts = (aggregate.get("ratings") or {}).get("summary_texts") or []
        observed_at = aggregate["window_end"].isoformat() if aggregate.get("window_end") else None
        return [{"text": t, "source": "파일 기반 리뷰 분석 (검수 승인)", "observed_at": observed_at}
                for t in texts[:limit]]

    def get_review_authenticity(self, product_key: str) -> dict:
        """[3-C] get_review_authenticity 계약 (기획서 §10-6).
        {orig_rating, cleaned_rating, cleanse_ratio, axis_scores, total_reviews,
         top_summaries, confidence_note}

        DB 경로 미구현 — [3-B]/[3-C]는 지금 파일 기반 ProductRiskStore(관계·행동 축)를
        쓴다(review_service.get_summary). 이 메서드는 그 계약의 자리를 남겨 둘 뿐 호출되지
        않는다."""
        raise NotImplementedError

    # ── P8 파일 기반 분석 적재 (import_review_analysis.py가 호출) ──
    def get_or_create_source(self, name: str) -> UUID:
        row = self._one("SELECT id FROM evidence.source WHERE name=%s", (name,))
        if row is None:
            row = self._one(
                "INSERT INTO evidence.source(name,source_type) VALUES (%s,'derived') RETURNING id", (name,))
        return row["id"]

    def upsert_review_summary(self, *, subject_id: UUID, source_id: UUID, external_review_key: str,
                              original_url: str, normalized_rating, collected_at,
                              processing_version: str, cleaning_status: str,
                              exclusion_reason: str | None = None, summary: str) -> UUID:
        """단일 표본(sample+label) 한 행. (source_id,external_review_key,processing_version)
        UNIQUE(0002_unique.sql review_summary_external_key)로 같은 파일 재적재가 자연히
        멱등이 된다 — 내용이 같으면 그대로, 달라지면 갱신(§ import는 같은 (id,버전) 조합에는
        같은 내용만 오도록 사전에 검증한다)."""
        return self._one(
            """INSERT INTO evidence.review_summary
                 (subject_id,source_id,origin,external_review_key,original_url,summary,
                  normalized_rating,collected_at,processing_version,cleaning_status,exclusion_reason)
               VALUES (%s,%s,'external',%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (source_id,external_review_key,processing_version)
                 WHERE external_review_key IS NOT NULL DO UPDATE SET
                 summary=EXCLUDED.summary, normalized_rating=EXCLUDED.normalized_rating,
                 cleaning_status=EXCLUDED.cleaning_status, exclusion_reason=EXCLUDED.exclusion_reason,
                 updated_at=now()
               RETURNING id""",
            (subject_id, source_id, external_review_key, original_url, summary, normalized_rating,
             collected_at, processing_version, cleaning_status, exclusion_reason))["id"]

    def replace_aggregate(self, *, subject_id: UUID, domain_version_id: UUID, source_scope: str,
                          processing_version: str, window_start, window_end,
                          analyzed_count: int, excluded_count: int, retained_count: int,
                          ratings: dict, axis_scores: dict,
                          members: list[dict]) -> dict:
        """P8 IMPLEMENTATION2 "Transactions atomically replace/current-mark summary +
        aggregate + aggregate_members, while preserving provenance": 같은
        (subject,domain_version,scope)의 기존 `ready` 행은 `stale`로 내리고 새 행을
        `ready`로 올린다 — UPDATE로 내용을 덮지 않아 이전 버전이 감사 이력으로 남는다.

        같은 processing_version이 내용까지 동일하게 다시 들어오면(재실행) 아무 것도
        만들지 않고 기존 행을 그대로 반환한다(멱등). 같은 version인데 내용이 다르면
        조용한 덮어쓰기 대신 명시적으로 거부한다 — 버전 이름은 그 내용의 식별자여야 한다."""
        existing = self.get_summary(subject_id, domain_version_id=domain_version_id, source_scope=source_scope)
        if existing is not None and existing["processing_version"] == processing_version:
            same = (existing["analyzed_count"] == analyzed_count and existing["excluded_count"] == excluded_count
                    and existing["retained_count"] == retained_count and dict(existing["ratings"]) == ratings)
            if same:
                return {"status": "skipped_idempotent", "aggregate_id": existing["id"]}
            raise ValueError(
                f"aggregate_version_conflict:{processing_version} — same version, different computed content")
        self._exec(
            """UPDATE evidence.review_aggregate SET status='stale', updated_at=now()
               WHERE subject_id=%s AND domain_version_id=%s AND source_scope=%s AND status='ready'""",
            (subject_id, domain_version_id, source_scope))
        row = self._one(
            """INSERT INTO evidence.review_aggregate
                 (subject_id,domain_version_id,source_scope,processing_version,window_start,window_end,
                  analyzed_count,excluded_count,retained_count,ratings,axis_scores,status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ready') RETURNING id""",
            (subject_id, domain_version_id, source_scope, processing_version, window_start, window_end,
             analyzed_count, excluded_count, retained_count, Jsonb(ratings), Jsonb(axis_scores)))
        aggregate_id = row["id"]
        for m in members:
            self._exec(
                """INSERT INTO evidence.review_aggregate_member(aggregate_id,summary_id,disposition,weight)
                   VALUES (%s,%s,%s,%s) ON CONFLICT (aggregate_id,summary_id) DO NOTHING""",
                (aggregate_id, m["summary_id"], m["disposition"], m.get("weight", 1)))
        return {"status": "imported", "aggregate_id": aggregate_id}


# ─────────────────────────────────────────────────────────────────────────────
# 오프라인 산출물 리더 — DB 연결 전까지 [3-B]/[3-C]/S5 가 읽는 자리
# ─────────────────────────────────────────────────────────────────────────────
class ProductRiskStore:
    """`review_cleanse_worker` 가 만든 `*_product_risk.json` 을 읽어 계약 모양으로 낸다.

    관계·행동 축은 **상품 단위 관측 사실**만 낸다. 조작 라벨이 없으므로
    `cleaned_rating`·`cleanse_ratio` 는 채우지 않는다(None) — 탐지기 없이 하향 평점을
    만들면 "조작을 걸러낸 하향" 과 "만족 고객을 걸러낸 하향" 을 구별할 수 없다.
    소비자 노출 여부는 별도 결정 사항이고, 이 리더는 그 결정을 선점하지 않는다.
    """

    # 랭킹용으로 "대조군 중앙값 대비 배수" 를 보는 관측값. 값이 클수록 몰림·다작 쪽.
    # one_off_rate(1건 계정 비율)는 뺐다 — 실측 라벨(Hollenbeck)에서 방향이 반대로 나왔는데(AUC 0.065)
    # 그 자료의 표집 구조(캠페인 리뷰어는 여러 상품에 나타난다) 탓일 수 있어 어느 방향도 믿을 수 없다.
    # 카드에는 그대로 보이고, 랭킹 신호에서만 뺀다. burst7 은 같은 라벨에서 걸린 상품의 82.9% 가
    # 양성(기저율 42.8%), prolific_rate 는 단독 AUC 0.797 로 방향이 맞았다.
    EXCESS_KEYS = ("burst7", "prolific_rate")

    # 산출물이 갖춰야 하는 최상위 키. 손으로 전달되는 5MB 파일이라 잘리거나 다른 파일이
    # 올 수 있다 — 그때 KeyError 로 추천 전체가 죽으면 안 된다(호출자가 "관측 없음" 으로 다룬다).
    REQUIRED_KEYS = ("meta", "controls", "products", "cards")

    def __init__(self, path: str | Path, alias_csv: str | Path | None = None):
        self.path = Path(path)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{self.path.name}: 최상위가 객체가 아니다")
        missing = [k for k in self.REQUIRED_KEYS if k not in data]
        if missing:
            raise ValueError(f"{self.path.name}: 필수 키 없음 {missing} — 이 배치의 산출물이 아니다")
        self.meta: dict = data["meta"]
        self.controls: dict = data["controls"]
        self.products: dict = data["products"]
        # product_key 없는 카드는 건너뛴다 — 한 항목이 깨졌다고 전체를 버리지 않는다
        self.cards: dict = {c["product_key"]: c for grp in data["cards"].values() for c in grp
                            if isinstance(c, dict) and c.get("product_key")}
        # 데모 부품 슬러그 → ASIN (scripts/map_parts_to_asin.py). 엔진 키와 요약 키 둘 다 받는다
        self.alias: dict[str, str] = {}
        # ASIN 이 없는 행의 note ("데이터 기간(~2023-09) 밖: 2024-01 출시" · "후보 없음") — 관측이 없는
        # 이유를 갈라 말하려면 이게 필요하다. 문턱 미만과 기간 밖을 같은 말로 내면 안 된다.
        self.map_notes: dict[str, str] = {}
        if alias_csv and Path(alias_csv).exists():
            import csv
            with open(alias_csv, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    for k in (r.get("product_key"), r.get("summary_key")):
                        if not k:
                            continue
                        if r.get("asin"):
                            self.alias[k] = r["asin"]
                        else:
                            self.map_notes[k] = r.get("note") or ""

    def resolve(self, key: str) -> str:
        return self.alias.get(key, key)

    COVERAGE_OBSERVED = "observed"
    COVERAGE_BELOW_THRESHOLD = "below_threshold"   # ASIN 은 있는데 산출물에 없다 — 리뷰 수 문턱 미만
    COVERAGE_OUT_OF_PERIOD = "out_of_period"       # 데이터 기간 뒤 출시
    COVERAGE_NO_MATCH = "no_match"                 # 원천 데이터에서 상품을 못 찾았다
    COVERAGE_UNMAPPED = "unmapped"                 # 매핑 표에 없는 키

    def coverage(self, key: str) -> tuple[str, str]:
        """(왜 관측이 있거나 없는지, 매핑 표의 note). 산출물이 있는데도 관측이 없는 이유를 원인별로 낸다."""
        if self.get(key) is not None:
            return self.COVERAGE_OBSERVED, ""
        if key in self.alias:
            return self.COVERAGE_BELOW_THRESHOLD, ""
        note = self.map_notes.get(key)
        if note is None:
            return self.COVERAGE_UNMAPPED, ""
        if note.startswith("데이터 기간"):
            return self.COVERAGE_OUT_OF_PERIOD, note
        return self.COVERAGE_NO_MATCH, note

    def get(self, product_key: str) -> dict | None:
        return self.products.get(self.resolve(product_key))

    LAUNCH_WINDOW_DAYS = 7

    @classmethod
    def is_launch_burst(cls, f: dict) -> bool:
        """몰림 구간이 그 상품의 첫 리뷰로부터 LAUNCH_WINDOW_DAYS 안에 있나.

        규칙을 여기 한 곳에 둔다 — `excess()`(랭킹에서 뺀다)와 `observations()`(카드에 이유를
        적는다)가 같은 판정을 써야 한다. 같은 규칙을 두 곳에 쓰다 갈라진 적이 있다.
        """
        start, first = f.get("burst7_start_day"), f.get("first_day")
        return start is not None and first is not None and start - first <= cls.LAUNCH_WINDOW_DAYS

    def excess(self, product_key: str) -> list[tuple[str, float, float]]:
        """대조군 중앙값과 나란히 둔 관측값 — (지표, 값, 중앙값). 판정이 아니라 '검토자가 볼 것' 의 목록.

        출시 첫 주의 몰림은 뺀다 — 그건 조작이 아니라 출시다. 카드에는 그대로 보이고(이유도 적는다),
        랭킹 신호에서만 뺀다. PC 부품 산출물 실측: 몰림이 중앙값 2배를 넘는 상품 915개 중 **109개
        (11.9%)** 가 출시 첫 주였다(Electronics 전체에서는 약 14%).

        **출시주가 아니라고 조작인 것은 아니다.** 남는 806개에도 할인·이벤트·인플루언서 언급·재입고·
        시즌성·리뷰 요청 메일 일괄 발송 같은 무해한 설명이 그대로 남아 있고, 이 데이터에는 조작
        라벨이 없어 그중 몇 %가 조작인지 우리는 모른다. 그래서 판정하지 않고 관측 사실만 낸다.
        """
        f = self.get(product_key)
        if not f:
            return []
        launch_burst = self.is_launch_burst(f)
        out = []
        for k in self.EXCESS_KEYS:
            if k == "burst7" and launch_burst:
                continue
            v, m = f.get(k), self.controls.get(k)
            # 중앙값이 0 이면 "몇 배" 가 정의되지 않아 이 지표는 조용히 빠진다 — 대조군이 그 지표를
            # 거의 안 갖는 데이터(예: 다작 계정이 드문 표본)에서 규칙이 몰림 하나로 줄어드는 이유.
            if v is not None and m:
                out.append((k, float(v), float(m)))
        return out

    def observations(self, product_key: str, lang: str = "ko") -> list[str]:
        """카드가 있으면 카드 문장, 없으면 특징 표에서 핵심 셋만 문장으로.
        영어는 카드 문장(배치가 한국어로 적어 둔 것)을 쓰지 않고 특징 표의 숫자로 다시 렌더한다."""
        asin = self.resolve(product_key)
        c = self.cards.get(asin)
        if c and lang != "en":
            return list(c["observations"])
        f = self.products.get(asin)
        if not f:
            return []
        m = self.controls
        if lang == "en":
            burst = (f"{int(f['burst7_count'])} of {int(f['n'])} reviews ({100*f['burst7']:.1f}%) arrived within a 7-day window"
                     f" — median across products {100*m['burst7']:.1f}%")
            if self.is_launch_burst(f):
                burst += " (launch week — likely the release, not manipulation; excluded from the ranking signal)"
            return [
                burst,
                f"{int(f['shared_reviewers'])} reviewers also appear on other products ({int(f['deg'])} connected products)"
                f" — median {m['shared_reviewers']:.0f} / {m['deg']:.0f}",
                f"5-star share {100*f['p5']:.0f}% — median {100*m['p5']:.0f}%",
            ]
        # 출시 첫 주 몰림이면 그렇다고 적는다. 적지 않으면 검토자가 "중앙값의 3배인데 왜
        # 검토 권장이 안 붙었나" 를 알 수 없고, 반박에 필요한 사실을 우리가 쥐고 안 주는 것이 된다.
        burst = (f"리뷰 {int(f['n'])}건 중 {int(f['burst7_count'])}건({100*f['burst7']:.1f}%)이 7일 안에 몰림"
                 f" — 전체 상품 중앙값 {100*m['burst7']:.1f}%")
        if self.is_launch_burst(f):
            burst += " (출시 첫 주 — 조작이 아니라 출시일 수 있어 랭킹 신호에서 뺐다)"
        return [
            burst,
            f"리뷰어 {int(f['shared_reviewers'])}명이 다른 상품에서도 함께 나타남 (연결 상품 {int(f['deg'])}개)"
            f" — 중앙값 {m['shared_reviewers']:.0f}명 / {m['deg']:.0f}개",
            f"5점 비율 {100*f['p5']:.0f}% — 중앙값 {100*m['p5']:.0f}%",
        ]

    def get_review_authenticity(self, product_key: str, lang: str = "ko") -> dict:
        """[3-C] 계약 (기획서 §10-6) 과 같은 키. 채울 수 없는 값은 None 으로 두고 이유를 적는다."""
        en = lang == "en"
        f = self.get(product_key)
        if not f:
            return {"orig_rating": None, "cleaned_rating": None, "cleanse_ratio": None,
                    "axis_scores": {}, "total_reviews": 0, "top_summaries": [],
                    "confidence_note": ("No observation — below the review-count threshold or not in the data" if en
                                        else "관측 없음 — 리뷰 수가 산출 문턱 미만이거나 데이터에 없는 상품"),
                    "product_manipulation_risk": {"score": None, "evidence": [], "reliable_range": None}}
        return {
            "orig_rating": round(f["mean_rating"], 2),
            "cleaned_rating": None,
            "cleanse_ratio": None,
            "axis_scores": {},
            "total_reviews": int(f["n"]),
            "top_summaries": [],
            "confidence_note": (
                ("No manipulation labels — no cleaned rating or exclusion ratio is computed. "
                 "Below are product-level observations, not the authenticity of any single review.") if en else
                "조작 라벨 없음 — 정제 평점·제외 비율은 산출하지 않는다. "
                "아래는 상품 단위 관측 사실이며 개별 리뷰의 진위가 아니다."),
            "product_manipulation_risk": {
                "score": None,                       # 점수는 두지 않는다 (근거 카드 원칙: 반박 가능한 것만)
                "evidence": self.observations(product_key, lang),
                "reliable_range": bool(f["n"] >= self.meta.get("min_reviews", 30)),
                "controls": self.controls,
                "source": self.meta.get("source"),
                "product_ref": self.resolve(product_key),
            },
        }


_default_store: ProductRiskStore | None = None
_default_store_tried = False
_default_store_reason = "not_loaded"

# 산출물을 못 쓰는 이유. "관측 없음" 한 문장으로 뭉치면 팀원이 파일을 안 받았다는 것을
# 영원히 모른다 — 문턱 미만과 파일 없음은 화면에 같은 말로 나가면 안 된다.
RISK_STORE_OK = "ok"
RISK_STORE_MISSING = "missing"
RISK_STORE_INVALID = "invalid"
RISK_STORE_SCOPE_MISMATCH = "scope_mismatch"


def default_risk_store() -> ProductRiskStore | None:
    """config.REVIEW_RISK_JSON 의 산출물을 한 번만 읽어 공유한다. 못 쓰면 None — 호출자는 "관측 없음" 으로.

    못 쓰는 경우가 넷이고 이유를 `risk_store_reason()` 으로 남긴다: 파일 없음 · 읽기/형식 실패 ·
    대조군 범위 불일치 · 정상. 형식 실패로 추천이 죽지 않게 여기서 막는다.
    테스트는 `_default_store`·`_default_store_tried` 를 monkeypatch 한다."""
    global _default_store, _default_store_tried, _default_store_reason
    if not _default_store_tried:
        _default_store_tried = True
        from src.config import PARTS_ASIN_MAP, REVIEW_RISK_CONTROL_SCOPE, REVIEW_RISK_JSON
        if not REVIEW_RISK_JSON.exists():
            _default_store_reason = RISK_STORE_MISSING
            return None
        try:
            store = ProductRiskStore(REVIEW_RISK_JSON, PARTS_ASIN_MAP)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            _default_store_reason = f"{RISK_STORE_INVALID}: {exc}"
            return None
        scope = store.meta.get("control_scope")
        if REVIEW_RISK_CONTROL_SCOPE and scope != REVIEW_RISK_CONTROL_SCOPE:
            # 조용히 틀린 중앙값과 비교하는 것보다 관측을 안 내는 게 낫다
            _default_store_reason = f"{RISK_STORE_SCOPE_MISMATCH}: {scope!r} (기대 {REVIEW_RISK_CONTROL_SCOPE!r})"
            return None
        _default_store, _default_store_reason = store, RISK_STORE_OK
    return _default_store


def risk_store_reason() -> str:
    """산출물 상태 — RISK_STORE_OK 또는 이유 문자열. 적재를 아직 시도 안 했으면 시도한다."""
    default_risk_store()
    return _default_store_reason


def risk_store_note() -> str:
    """관측이 없을 때 화면에 붙일 "왜". 원인을 문턱 미만으로 뭉개지 않는다."""
    reason = risk_store_reason()
    if reason == RISK_STORE_OK:
        return "리뷰 수 문턱 미만이거나 데이터 기간 밖"
    if reason == RISK_STORE_MISSING:
        from src.config import REVIEW_RISK_JSON
        return f"산출물 미탑재 — {REVIEW_RISK_JSON.name}"
    if reason.startswith(RISK_STORE_SCOPE_MISMATCH):
        return f"대조군 범위 불일치 — {reason.split(': ', 1)[-1]}"
    return f"산출물을 읽지 못함 — {reason.split(': ', 1)[-1]}"


# 관측 지표 → 사람이 읽는 이름. 랭킹 flags 와 [5] 설명이 같이 쓴다
OBS_LABEL = {"burst7": "7일 몰림", "one_off_rate": "1건 계정 비율", "prolific_rate": "다작 계정 비율"}

# [3-B] 가 Candidate.flags(list[str]) 에 남기고 [5] 가 읽는 관측 플래그. 팀 DTO 를 바꾸지 않으려고
# 문자열이지만, 만들고 읽는 곳은 여기 둘뿐이다.
OBS_FLAG_PREFIX = "REVIEW_OBS:"
OBS_FLAG_OBSERVED = OBS_FLAG_PREFIX + "observed"       # 관측됨 · 중앙값 초과 없음


def format_obs_flag(key: str, value: float, median: float, excess: float) -> str:
    """예: REVIEW_OBS:burst7=0.184>2x0.055"""
    return f"{OBS_FLAG_PREFIX}{key}={value:.3f}>{excess:g}x{median:.3f}"


def parse_obs_flag(flag: str) -> tuple[str, float, float] | None:
    """(지표, 값, 중앙값). 관측됨 표지·다른 플래그는 None."""
    if not flag.startswith(OBS_FLAG_PREFIX) or flag == OBS_FLAG_OBSERVED:
        return None
    body = flag[len(OBS_FLAG_PREFIX):]
    key, rest = body.split("=", 1)
    value, rhs = rest.split(">", 1)
    return key, float(value), float(rhs.split("x", 1)[1])


def is_obs_flag(flag: str) -> bool:
    return flag.startswith(OBS_FLAG_PREFIX)


class ReviewSummaryDemoFile:
    """`data/review_summaries.json`(합성 데모) 리더 — 항목별 평가·대표 요약 3건의 유일한 출처.

    행마다 `is_synthetic: true` 와 `cleaned_rating_note` 가 붙어 있다(docs/decisions/0001).
    여기서 읽은 `cleaned_rating`·`cleanse_ratio` 는 계약의 최상위 필드로 올리지 않고
    `synthetic_demo` 블록에 그대로 둔다 — 화면이 표지를 붙여 보여주는 용도다.
    키는 요약 키(slugify)와 엔진 키(공백→하이픈) 둘 다 받는다.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        rows = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []
        self.rows: dict[str, dict] = {}
        for r in rows:
            self.rows[r["product_key"]] = r
            self.rows[r["product_name"].lower().replace(" ", "-")] = r

    def get(self, product_key: str) -> dict | None:
        return self.rows.get(product_key)


# ─────────────────────────────────────────────────────────────────────────────
# 규칙 기반 "의심 지표 2개+ 리뷰 수" 리더
# ─────────────────────────────────────────────────────────────────────────────
class SuspectCountFile:
    """`data/review_suspect_counts.json` 을 읽어 상품별 문장 하나로 낸다.

    **이 수는 조작으로 판정된 리뷰 수가 아니다.** 정의된 지표(몰림·다작 계정·1건 계정·
    단기 활동·구매 미확인) 중 2개 이상에 걸린 리뷰 수다. 리뷰 단위 라벨이 없어 정밀도를
    잴 수 없고, "2개 이상" 이라는 문턱도 근거로 정한 값이 아니다.

    그래서 문장에 **항상 셋을 같이** 낸다 — 건수 · 이항 95% CI · 전체 기준선. 숫자만 내면
    n=30 과 n=3,830 이 같은 무게로 읽힌다(실제로 n=37 의 21.6% 는 CI 가 [9.8, 38.2] 다).
    CI 하한이 기준선을 넘지 않으면 "구별되지 않음" 이라고 쓴다.
    """

    def __init__(self, path: str | Path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.method: dict = data.get("method", {})
        self.limits: list = data.get("limits", [])
        self.baseline: dict = data.get("baseline", {})
        self.products: dict = data.get("products", {})

    def get(self, product_key: str) -> dict | None:
        return self.products.get(product_key)

    def sentence(self, product_key: str, lang: str = "ko") -> str | None:
        """검토자가 읽을 한 줄. 없으면 None."""
        v = self.get(product_key)
        if not v or not v.get("n"):
            return None
        n, k = int(v["n"]), int(v["ge2"])
        lo, hi = (v.get("ci2") or [0.0, 100.0])[:2]
        base = self.baseline.get("rate_pct")
        if lang == "en":
            verdict = ""
            if base is not None:
                verdict = " · above the baseline" if lo > base else " · not distinguishable from the baseline"
            base_txt = f" (all demo products {base}%)" if base is not None else ""
            return (f"{k} of {n} reviews ({100*k/n:.1f}%) trip 2+ suspicion indicators"
                    f"{base_txt} — 95% CI [{lo}, {hi}]{verdict}")
        verdict = ""
        if base is not None:
            verdict = " · 기준선 초과" if lo > base else " · 기준선과 구별되지 않음"
        base_txt = f" (데모 상품 전체 {base}%)" if base is not None else ""
        return (f"리뷰 {n}건 중 {k}건({100*k/n:.1f}%)이 의심 지표 2개 이상에 걸림"
                f"{base_txt} — 95% 신뢰구간 [{lo}, {hi}]{verdict}")


_suspect_file: SuspectCountFile | None = None
_suspect_tried = False

# 문장 출처 표시 — 이 수가 판정이 아니라 규칙 집계라는 것을 문장과 함께 항상 붙인다
SUSPECT_SOURCE = "규칙 기반 집계 — 조작 판정 아님 (지표 2개+, 정답 라벨 없음)"


def default_suspect_counts() -> SuspectCountFile | None:
    """config.REVIEW_SUSPECT_COUNTS 를 한 번만 읽는다. 없거나 깨지면 None — 문장을 안 낸다."""
    global _suspect_file, _suspect_tried
    if not _suspect_tried:
        _suspect_tried = True
        from src.config import REVIEW_SUSPECT_COUNTS
        if REVIEW_SUSPECT_COUNTS.exists():
            try:
                _suspect_file = SuspectCountFile(REVIEW_SUSPECT_COUNTS)
            except (ValueError, OSError, json.JSONDecodeError):
                _suspect_file = None
    return _suspect_file
