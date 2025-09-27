"""Lightweight in-memory market data provider for demonstration purposes."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Iterable, Mapping, Tuple

from ..models import MarketDataPoint


@dataclass(frozen=True)
class MarketQuote:
    price: Decimal
    currency: str


DEFAULT_QUOTES: Dict[str, MarketQuote] = {
    "AAPL": MarketQuote(price=Decimal("189.54"), currency="USD"),
    "MSFT": MarketQuote(price=Decimal("338.11"), currency="USD"),
    "GOOGL": MarketQuote(price=Decimal("141.25"), currency="USD"),
    "AMZN": MarketQuote(price=Decimal("128.78"), currency="USD"),
    "META": MarketQuote(price=Decimal("297.35"), currency="USD"),
    "TSLA": MarketQuote(price=Decimal("256.55"), currency="USD"),
    "NVDA": MarketQuote(price=Decimal("430.90"), currency="USD"),
    "NFLX": MarketQuote(price=Decimal("410.12"), currency="USD"),
    "BABA": MarketQuote(price=Decimal("87.65"), currency="USD"),
    "ORCL": MarketQuote(price=Decimal("114.78"), currency="USD"),
}


class MarketDataProvider:
    """Provides read access to in-memory market data."""

    def __init__(self, quotes: Mapping[str, MarketQuote] | None = None) -> None:
        self._quotes: Dict[str, MarketQuote] = {
            symbol.upper(): quote for symbol, quote in (quotes or DEFAULT_QUOTES).items()
        }

    def snapshot(self) -> Dict[str, MarketQuote]:
        """Return a copy of the available market quotes."""

        return dict(self._quotes)

    def _quote_from_overrides(
        self, ticker: str, overrides: Mapping[str, MarketQuote] | None
    ) -> MarketQuote | None:
        if not overrides:
            return None
        return overrides.get(ticker.upper())

    def get_quote(
        self,
        ticker: str,
        overrides: Mapping[str, MarketQuote] | None = None,
    ) -> MarketQuote:
        normalized = ticker.upper()
        override_quote = self._quote_from_overrides(normalized, overrides)
        if override_quote is not None:
            return override_quote
        try:
            return self._quotes[normalized]
        except KeyError as exc:  # pragma: no cover - informative branch
            raise KeyError(f"No market data available for {ticker}") from exc

    @staticmethod
    def build_overrides(data_points: Iterable[MarketDataPoint] | None) -> Dict[str, MarketQuote]:
        """Convert API payload overrides into MarketQuote instances."""

        if not data_points:
            return {}
        overrides: Dict[str, MarketQuote] = {}
        for item in data_points:
            overrides[item.ticker.upper()] = MarketQuote(price=item.price, currency=item.currency)
        return overrides

    def merge(
        self, overrides: Mapping[str, MarketQuote] | None = None
    ) -> Dict[str, MarketQuote]:
        """Merge overrides with the provider snapshot."""

        merged = self.snapshot()
        if overrides:
            merged.update({k.upper(): v for k, v in overrides.items()})
        return merged
