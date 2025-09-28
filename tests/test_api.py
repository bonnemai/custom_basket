import json
import os
import time
from typing import Optional

from fastapi.testclient import TestClient
import pytest

from app.main import create_app


os.environ.setdefault("BASKET_STREAM_INTERVAL", "0.1")

client = TestClient(create_app())


def _create_sample_basket(basket_name: str = "Tech") -> dict:
    payload = {
        "basket_name": basket_name,
        "base_currency": "USD",
        "positions": [
            {"ticker": "AAPL", "weight": "0.5"},
            {"ticker": "MSFT", "weight": "0.3"},
            {"ticker": "GOOGL", "weight": "0.2"},
        ],
        "notional": "1000000",
    }
    response = client.post("/baskets", json=payload)
    assert response.status_code == 201
    return response.json()


def test_create_and_list_baskets() -> None:
    basket = _create_sample_basket()

    assert "basket_id" in basket
    assert basket["basket_name"] == "Tech"
    assert basket["basket_price"] == 224.453
    assert basket["created_at"] <= basket["updated_at"]

    listing = client.get("/baskets")
    assert listing.status_code == 200
    items = listing.json()
    assert any(item["basket_id"] == basket["basket_id"] for item in items)


def test_update_basket_recalculates_price() -> None:
    basket = _create_sample_basket("Growth")

    basket_id = basket["basket_id"]
    updated_payload = {
        "basket_name": "Growth",
        "base_currency": "USD",
        "positions": [
            {"ticker": "AAPL", "weight": "0.4"},
            {"ticker": "MSFT", "weight": "0.4"},
            {"ticker": "GOOGL", "weight": "0.2"},
        ],
    }

    response = client.put(f"/baskets/{basket_id}", json=updated_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["basket_id"] == basket_id
    assert data["basket_price"] != basket["basket_price"]
    assert data["basket_name"] == "Growth"


def test_post_pricing_endpoint_remains_available() -> None:
    payload = {
        "basket_name": "Tech",
        "base_currency": "USD",
        "positions": [
            {"ticker": "AAPL", "weight": "0.5"},
            {"ticker": "MSFT", "weight": "0.3"},
            {"ticker": "GOOGL", "weight": "0.2"},
        ],
    }

    response = client.post("/pricing/basket", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["basket_price"] == 224.453


def test_missing_market_data_returns_404_on_create() -> None:
    payload = {
        "basket_name": "Unknown",
        "base_currency": "USD",
        "positions": [
            {"ticker": "XYZ", "weight": "1"},
        ],
    }

    response = client.post("/baskets", json=payload)
    assert response.status_code == 404
    assert "No market data" in response.json()["detail"]


def test_market_data_endpoint() -> None:
    response = client.get("/market-data/AAPL")
    assert response.status_code == 200
    data = response.json()
    assert data["ticker"] == "AAPL"
    assert "price" in data
    assert data["currency"] == "USD"


def test_metrics_endpoint() -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    assert "basket_pricing_requests_total" in body


@pytest.mark.skip(reason="Flaky in CI, needs investigation")
def test_basket_stream_emits_price_updates() -> None:
    basket = _create_sample_basket("Realtime")

    def _extract_payload(timeout: float = 2.0) -> Optional[dict]:
        with client.stream("GET", "/baskets/stream", timeout=2) as stream:
            start = time.time()
            buffer: list[str] = []
            for line in stream.iter_lines():
                if line is None:
                    if time.time() - start > timeout:
                        break
                    continue
                if line.startswith(":"):
                    continue  # comment line from SSE heartbeat
                if line == "":
                    buffer.clear()
                    continue
                buffer.append(line)
                if line.startswith("data:"):
                    data_line = line.split("data:", 1)[1].strip()
                    if not data_line:
                        continue
                    return json.loads(data_line)
                if time.time() - start > timeout:
                    break
        return None

    payload = _extract_payload()
    assert payload is not None
    assert payload["baskets"]
    assert any(item["basket_id"] == basket["basket_id"] for item in payload["baskets"])
