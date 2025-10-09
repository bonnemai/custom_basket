"""Utility helpers to fetch delayed real-time quotes from EODHD."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import AsyncIterator, Dict, Iterable, Mapping

import httpx


logger = logging.getLogger(__name__)


class EODHDDelayedClient:
    """Retrieve delayed intraday quotes from the EODHD REST API."""

    def __init__(
        self,
        api_token: str | None = None,
        *,
        session: httpx.AsyncClient | None = None,
        base_url: str = "https://eodhd.com/api/real-time",
    ) -> None:
        token = api_token or os.getenv("EODHD_API_TOKEN")
        if not token:
            raise ValueError("EODHD_API_TOKEN environment variable is required")

        self._token = token
        self._client = session
        self._base_url = base_url.rstrip("/")
        self._owns_client = session is None

    @staticmethod
    def _normalize_symbols(tickers: Iterable[str]) -> list[str]:
        symbols: set[str] = set()
        for ticker in tickers:
            if not ticker or not ticker.strip():
                continue
            normalized = ticker.upper()
            if "." not in normalized:
                normalized = f"{normalized}.US"
            symbols.add(normalized)
        return sorted(symbols)

    async def _client_instance(self) -> httpx.AsyncClient:
        if self._client is None:
            timeout = httpx.Timeout(5.0, connect=5.0)
            self._client = httpx.AsyncClient(timeout=timeout)
        return self._client

    async def fetch_quotes(self, tickers: Iterable[str]) -> Dict[str, Mapping[str, object]]:
        symbols = self._normalize_symbols(tickers)
        if not symbols:
            return {}

        symbol_path = ",".join(symbols)
        client = await self._client_instance()
        params = {"api_token": self._token, "fmt": "json"}
        url = f"{self._base_url}/{symbol_path}"

        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # pragma: no cover - network errors require live API
            logger.warning("EODHD request failed: %s", exc)
            return {}

        entries: Iterable[Mapping[str, object]]
        if isinstance(payload, list):
            entries = payload
        elif isinstance(payload, Mapping):
            entries = [payload]
        else:
            logger.debug("Unexpected payload type from EODHD: %r", type(payload))
            return {}

        quotes: Dict[str, Mapping[str, object]] = {}
        for entry in entries:
            code = entry.get("code") or entry.get("symbol") or entry.get("ticker")
            if not isinstance(code, str):
                continue
            base_symbol = code.split(".", 1)[0].upper()
            quotes[base_symbol] = entry
        return quotes

    async def stream_quotes(
        self,
        tickers: Iterable[str],
        *,
        interval: float = 5.0,
        max_updates: int | None = None,
    ) -> AsyncIterator[Dict[str, Mapping[str, object]]]:
        count = 0
        while True:
            yield await self.fetch_quotes(tickers)
            count += 1
            if max_updates is not None and count >= max_updates:
                break
            await asyncio.sleep(interval)

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None


async def _demo() -> None:
    symbols_env = os.getenv("EODHD_SYMBOLS", "AAPL,MSFT,SPY")
    tickers = [symbol.strip() for symbol in symbols_env.split(",") if symbol.strip()]
    interval = float(os.getenv("EODHD_POLL_INTERVAL", "10"))

    client = EODHDDelayedClient()
    try:
        async for quotes in client.stream_quotes(tickers, interval=interval, max_updates=3):
            logger.info("Received %d quotes", len(quotes))
            for symbol, data in quotes.items():
                price = data.get("close") or data.get("price") or data.get("last")
                logger.info("%s -> %s", symbol, price)
    finally:
        await client.aclose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(_demo())
