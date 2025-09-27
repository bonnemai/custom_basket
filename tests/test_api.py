from fastapi.testclient import TestClient

from app.main import create_app


client = TestClient(create_app())


def test_price_basket_endpoint() -> None:
    payload = {
        "basket_name": "Tech",
        "base_currency": "USD",
        "positions": [
            {"ticker": "AAPL", "weight": "0.5"},
            {"ticker": "MSFT", "weight": "0.3"},
            {"ticker": "GOOGL", "weight": "0.2"},
        ],
        "notional": "1000000",
    }

    response = client.post("/pricing/basket", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["basket_name"] == "Tech"
    assert data["basket_price"] == 224.453
    assert len(data["positions"]) == 3


def test_market_data_endpoint() -> None:
    response = client.get("/market-data/AAPL")
    assert response.status_code == 200
    data = response.json()
    assert data["ticker"] == "AAPL"
    assert "price" in data
    assert data["currency"] == "USD"


def test_missing_market_data_returns_404() -> None:
    payload = {
        "basket_name": "Unknown",
        "base_currency": "USD",
        "positions": [
            {"ticker": "XYZ", "weight": "1"},
        ],
    }

    response = client.post("/pricing/basket", json=payload)
    assert response.status_code == 404
    assert "No market data" in response.json()["detail"]


def test_metrics_endpoint() -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    assert 'basket_pricing_requests_total' in body
