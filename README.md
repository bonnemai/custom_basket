# Delta-One Custom Basket Pricing Service

Change of specs: Delta One Custom Basket Pricer: 
- one POST Restul Endpoint to create a new Custom Basket: keep it in the cache
- one PUT/ PATCH to update the Basket
- GET to get all baskets
- Create Server Sent Event to publish the prices of all baskets using the spots from eodhd.com

A FastAPI backend for valuing bespoke delta-one baskets. It ingests a basket definition with constituent weights, applies market data and FX conversions, and returns indicative pricing alongside position-level analytics.

## Features
- Persistent in-memory cache for created baskets with RESTful create, update, and list endpoints.
- Spot pricing for custom baskets with optional target notional allocation.
- Automatically sources indicative prices and FX rates from the built-in dataset with optional EODHD intraday refresh.
- Position level breakdown showing normalized weights, contributions, and share quantities.
- Server-Sent Events feed that streams basket prices using EODHD real-time data when available (falls back to static quotes otherwise).
- Prometheus-compatible `/metrics` endpoint with request counters and latency histograms.

## Project Layout
```text
app/
  main.py             # FastAPI wiring
  models.py           # Pydantic request/response contracts
  services/
    market_data.py    # Sample market data provider
    pricing.py        # Pricing engine & FX handler
tests/
  test_api.py         # API contract tests
  test_pricing_service.py  # Core pricing logic tests
```

## Getting Started
### Using uv (recommended)
1. Install [uv](https://docs.astral.sh/uv/) if needed.
2. From the project root, run:
   ```bash
   uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
   The first invocation resolves and caches dependencies based on `pyproject.toml`.

### Using virtualenv + pip
1. Create a virtual environment and install dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e .[dev]
   ```
2. Start the API:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

## API Highlights
- `POST /baskets` – create and price a basket, persisting it in the cache (response includes `basket_id`).
- `PUT/PATCH /baskets/{basket_id}` – replace an existing basket definition and recalculate pricing.
- `GET /baskets` – retrieve the current cached state of all baskets.
- `GET /baskets/stream` – Server-Sent Events endpoint that broadcasts periodic price snapshots for all baskets.
- `POST /pricing/basket` – legacy pricing endpoint that prices a request without persisting it.

### Sample Requests
Create and persist a basket:
```bash
curl -X POST http://localhost:8000/baskets \
     -H "Content-Type: application/json" \
     -d '{
           "basket_name": "Tech",
           "base_currency": "USD",
           "positions": [
             {"ticker": "AAPL", "weight": "0.5"},
             {"ticker": "MSFT", "weight": "0.3"},
             {"ticker": "GOOGL", "weight": "0.2"}
           ]
         }'
```

Stream live prices (requires `EODHD_API_TOKEN`; falls back to static quotes otherwise):
```bash
curl http://localhost:8000/baskets/stream
```

## Running Tests
- With uv: `make unit-tests`
- With an activated virtualenv: `pytest`

## Docker
- Build the runtime image:
  ```bash
  docker build -t custom-basket .
  ```
- Run the service:
  ```bash
  docker run --rm -p 8000:8000 custom-basket
  ```
- Execute the unit-test build target:
  ```bash
  docker build --target unit-tests .
  ```

## Observability
- `/metrics` returns Prometheus exposition format with `basket_pricing_requests_total` and `basket_pricing_duration_seconds`.
  Scrape it from FastAPI directly or via the container port.

## Notes
- The bundled market and FX data is illustrative only. Supply overrides in the request payload to price instruments outside the sample universe.
- Normalized weights are based on gross exposure; a warning is returned if the provided weights do not sum to one.
