import asyncio
from typing import Any, Dict, Iterable, List, Mapping

import pytest

from app.services.real_time import EODHDDelayedClient


class _DummyResponse:
    def __init__(self, payload: Any, *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self) -> Any:
        return self._payload


class _DummyClient:
    def __init__(self, payloads: Iterable[Any]) -> None:
        self._payloads: List[Any] = list(payloads)
        self.calls: list[tuple[str, Dict[str, str]]] = []

    async def get(self, url: str, *, params: Mapping[str, str]) -> _DummyResponse:
        self.calls.append((url, dict(params)))
        payload = self._payloads.pop(0)
        return _DummyResponse(payload)

    async def aclose(self) -> None:  # pragma: no cover - not exercised in tests
        pass


def _run(coro):
    return asyncio.run(coro)


def test_normalize_symbols_deduplicates_and_formats() -> None:
    values = ["aapl", "AAPL", "msft.us", "", "  "]
    assert EODHDDelayedClient._normalize_symbols(values) == ["AAPL.US", "MSFT.US"]


def test_fetch_quotes_returns_entries_from_list_payload() -> None:
    client = _DummyClient([
        [
            {"code": "AAPL.US", "price": 101.5},
            {"symbol": "MSFT.US", "last": 320.0},
        ]
    ])
    service = EODHDDelayedClient(api_token="token", session=client, base_url="https://example.com")

    quotes = _run(service.fetch_quotes(["aapl", "msft"]))

    assert quotes == {
        "AAPL": {"code": "AAPL.US", "price": 101.5},
        "MSFT": {"symbol": "MSFT.US", "last": 320.0},
    }
    assert client.calls[0][0].endswith("/AAPL.US,MSFT.US")


def test_fetch_quotes_handles_single_mapping_payload() -> None:
    payload = {"code": "SPY.US", "close": 430.2}
    client = _DummyClient([payload])
    service = EODHDDelayedClient(api_token="token", session=client)

    quotes = _run(service.fetch_quotes(["spy"]))

    assert quotes == {"SPY": payload}


def test_fetch_quotes_returns_empty_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailClient(_DummyClient):
        async def get(self, url: str, *, params: Mapping[str, str]) -> _DummyResponse:  # type: ignore[override]
            raise RuntimeError("boom")

    service = EODHDDelayedClient(api_token="token", session=_FailClient([]))
    assert _run(service.fetch_quotes(["aapl"])) == {}


def test_stream_quotes_yields_requested_number(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    class _CountingClient(_DummyClient):
        async def get(self, url: str, *, params: Mapping[str, str]) -> _DummyResponse:  # type: ignore[override]
            calls.append(len(calls) + 1)
            return _DummyResponse({"code": "AAPL.US", "price": calls[-1]})

    async def _no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    service = EODHDDelayedClient(api_token="token", session=_CountingClient([]))

    async def _collect() -> list[Dict[str, Any]]:
        updates = []
        async for payload in service.stream_quotes(["aapl"], interval=0.0, max_updates=3):
            updates.append(payload)
        return updates

    updates = _run(_collect())

    assert len(updates) == 3
    assert all("AAPL" in payload for payload in updates)

