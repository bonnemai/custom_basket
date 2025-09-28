"""In-memory storage for basket definitions and their latest pricing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Dict, Iterable, List

from ..models import BasketPricingResponse, BasketRequest


@dataclass
class CachedBasket:
    """Represents a basket stored in memory with its latest valuation."""

    basket_id: str
    definition: BasketRequest
    pricing: BasketPricingResponse
    created_at: datetime
    updated_at: datetime


class BasketCache:
    """Thread-safe in-memory cache for baskets."""

    def __init__(self) -> None:
        self._items: Dict[str, CachedBasket] = {}
        self._lock = RLock()

    def _now(self) -> datetime:
        return datetime.now(tz=timezone.utc)

    def upsert(self, basket_id: str, definition: BasketRequest, pricing: BasketPricingResponse) -> CachedBasket:
        with self._lock:
            now = self._now()
            definition_copy = definition.model_copy(deep=True)
            pricing_copy = pricing.model_copy(deep=True)
            if basket_id in self._items:
                cached = self._items[basket_id]
                cached.definition = definition_copy
                cached.pricing = pricing_copy
                cached.updated_at = now
                return cached
            cached = CachedBasket(
                basket_id=basket_id,
                definition=definition_copy,
                pricing=pricing_copy,
                created_at=now,
                updated_at=now,
            )
            self._items[basket_id] = cached
            return cached

    def update_pricing(self, basket_id: str, pricing: BasketPricingResponse) -> None:
        with self._lock:
            cached = self._items.get(basket_id)
            if cached is None:
                return
            cached.pricing = pricing.model_copy(deep=True)
            cached.updated_at = self._now()

    def get(self, basket_id: str) -> CachedBasket | None:
        with self._lock:
            cached = self._items.get(basket_id)
            if cached is None:
                return None
            return CachedBasket(
                basket_id=cached.basket_id,
                definition=cached.definition.model_copy(deep=True),
                pricing=cached.pricing.model_copy(deep=True),
                created_at=cached.created_at,
                updated_at=cached.updated_at,
            )

    def remove(self, basket_id: str) -> None:
        with self._lock:
            self._items.pop(basket_id, None)

    def list(self) -> List[CachedBasket]:
        with self._lock:
            return [
                CachedBasket(
                    basket_id=item.basket_id,
                    definition=item.definition.model_copy(deep=True),
                    pricing=item.pricing.model_copy(deep=True),
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                )
                for item in self._items.values()
            ]

    def ids(self) -> Iterable[str]:
        with self._lock:
            return list(self._items.keys())
