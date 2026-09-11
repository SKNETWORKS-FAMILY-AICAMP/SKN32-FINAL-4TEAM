"""catalog.* 저장소 — product / product_variant / product_category(_membership) /
product_fact / merchant / offer / offer_observation.

데모: 후보·가격은 합성 카탈로그(catalog_repo.py) 사용. 이 repo 는 최종에서
제휴 커머스 API + DB 조인으로 채운다. product_fact 는 검증 실행기의 규격 기준(§20).
"""
from __future__ import annotations

from uuid import UUID

from src.db.base import Repo


class ProductRepo(Repo):
    def upsert_product(self, *, name: str, brand: str, model: str, product_type: str,
                       attributes: dict) -> UUID:
        raise NotImplementedError

    def upsert_variant(self, product_id: UUID, variant_key: str, *, attributes: dict,
                       pack_quantity=1, gtin: str | None = None) -> UUID:
        raise NotImplementedError

    def add_fact(self, product_id: UUID, attribute_key: str, value: dict, *,
                 evidence_id: UUID, variant_id: UUID | None = None,
                 unit_code: str | None = None, observed_at) -> UUID:
        """근거 있는 규격 속성. verified + active evidence 만 검증 실행기에 투입(§20)."""
        raise NotImplementedError

    def verified_facts(self, product_id: UUID, variant_id: UUID | None) -> list[dict]:
        """옵션 한정 fact 우선, 모델 공통 fact 다음. 충돌 시 unknown(§20)."""
        raise NotImplementedError

    def upsert_offer(self, variant_id: UUID, merchant_id: UUID, external_offer_id: str,
                     purchase_url: str) -> UUID:
        raise NotImplementedError

    def add_observation(self, offer_id: UUID, source_id: UUID, *, observed_at,
                        price, stock_status: str, quality_status: str,
                        pricing_terms: dict) -> UUID:
        """과거 행 불변. valid 면 price 필수."""
        raise NotImplementedError

    def latest_observation(self, offer_id: UUID) -> dict | None:
        raise NotImplementedError
