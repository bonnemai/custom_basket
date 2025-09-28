"""Spot price providers with optional integration to EODHD real-time data."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Iterable, Mapping

import httpx

from .market_data import MarketDataProvider, MarketQuote


logger = logging.getLogger(__name__)


class SpotProvider:
    """Expose consolidated spot prices for a collection of tickers."""

    def __init__(
        self,
        market_data_provider: MarketDataProvider,
        api_token: str | None = None,
        session: httpx.AsyncClient | None = None,
    ) -> None:
        self._market_data_provider = market_data_provider
        self._api_token = api_token
        self._client = session

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            timeout = httpx.Timeout(5.0, connect=5.0)
            self._client = httpx.AsyncClient(timeout=timeout)
        return self._client

    @staticmethod
    def _to_eodhd_symbol(ticker: str) -> str:
        normalized = ticker.upper()
        if "." in normalized:
            return normalized
        return f"{normalized}.US"

    @staticmethod
    def _base_ticker(eodhd_symbol: str) -> str:
        if "." in eodhd_symbol:
            return eodhd_symbol.split(".", 1)[0]
        return eodhd_symbol

    @staticmethod
    def _extract_price(entry: Mapping[str, object]) -> Decimal | None:
        for field in ("close", "adjusted_close", "price", "last", "close_prev"):
            value = entry.get(field)
            if value is None:
                continue
            try:
                return Decimal(str(value))
            except (ValueError, ArithmeticError):
                continue
        return None

    async def _fetch_from_eodhd(self, tickers: Iterable[str]) -> Dict[str, MarketQuote]:
        if not self._api_token:
            return {}

        symbols = {self._to_eodhd_symbol(ticker) for ticker in tickers}
        if not symbols:
            return {}

        client = await self._get_client()
        # EODHD accepts comma separated symbols for real-time endpoint.
        symbol_path = ",".join(sorted(symbols))
        url = f"https://eodhd.com/api/real-time/{symbol_path}"
        params = {"api_token": self._api_token, "fmt": "json"}

        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # pragma: no cover - network errors not triggered in tests
            logger.warning("Unable to retrieve quotes from EODHD: %s", exc)
            return {}

        entries: Iterable[Mapping[str, object]]
        if isinstance(payload, list):
            entries = payload
        elif isinstance(payload, dict):
            entries = [payload]
        else:
            logger.debug("Unexpected payload type from EODHD: %r", type(payload))
            return {}

        quotes: Dict[str, MarketQuote] = {}
        for entry in entries:
            code = entry.get("code") or entry.get("symbol") or entry.get("ticker")
            if not isinstance(code, str):
                continue
            ticker = self._base_ticker(code)
            price = self._extract_price(entry)
            if price is None:
                continue
            currency = entry.get("currency") if isinstance(entry.get("currency"), str) else "USD"
            quotes[ticker] = MarketQuote(price=price, currency=currency.upper())
        return quotes

    async def get_quotes(self, tickers: Iterable[str]) -> Dict[str, MarketQuote]:
        normalized = {ticker.upper() for ticker in tickers}
        if not normalized:
            return {}

        quotes: Dict[str, MarketQuote] = {}
        eodhd_quotes = await self._fetch_from_eodhd(normalized)
        quotes.update(eodhd_quotes)

        missing = normalized - set(quotes.keys())
        if missing:
            snapshot = self._market_data_provider.snapshot()
            for ticker in missing:
                if ticker in snapshot:
                    quotes[ticker] = snapshot[ticker]

        return quotes

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
