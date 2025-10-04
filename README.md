# Delta-One Custom Basket Pricing Service

https://github.com/bonnemai/custom_basket

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
### Dependencies
1. Install [uv](https://docs.astral.sh/uv/) (or create a virtualenv) and install the project:
   ```bash
   uv pip install -e .[dev]
   # or
   python3 -m venv .venv && source .venv/bin/activate && pip install -e .[dev]
   ```

### Local Lambda invocation
The container now targets AWS Lambda (arm64). Build and run it locally with the Lambda Runtime API exposed:
```bash
docker build -t custom-basket .
docker run --rm -p 9000:8080 custom-basket
```

Invoke the function by sending an API Gateway-style event to `http://localhost:9000/2015-03-31/functions/function/invocations`:
```bash
curl -X POST \
  "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -H "Content-Type: application/json" \
  -d '{
        "resource": "/baskets",
        "path": "/baskets",
        "httpMethod": "GET",
        "headers": {"accept": "application/json"},
        "requestContext": {"http": {"path": "/baskets", "method": "GET"}},
        "isBase64Encoded": false
      }'
```
Adjust `httpMethod`, `path`, and body for other endpoints. For automated checks, rely on `pytest`, which drives the FastAPI application directly.

## API Highlights
- `POST /baskets` – create and price a basket, persisting it in the cache (response includes `basket_id`).
- `PUT/PATCH /baskets/{basket_id}` – replace an existing basket definition and recalculate pricing.
- `GET /baskets` – retrieve the current cached state of all baskets.
- `GET /baskets/stream` – Server-Sent Events endpoint that broadcasts periodic price snapshots for all baskets.
- `POST /pricing/basket` – legacy pricing endpoint that prices a request without persisting it.

### Sample Requests
For example, to create a basket locally via Lambda emulation:
```bash
curl -X POST \
  "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -H "Content-Type: application/json" \
  -d '{
        "resource": "/baskets",
        "path": "/baskets",
        "httpMethod": "POST",
        "headers": {"content-type": "application/json"},
        "requestContext": {"http": {"path": "/baskets", "method": "POST"}},
        "body": "{\\"basket_name\\": \\"Tech\\", \\"base_currency\\": \\"USD\\", \\"positions\\": [{\\"ticker\\": \\"AAPL\\", \\"weight\\": \\"0.5\\"}, {\\"ticker\\": \\"MSFT\\", \\"weight\\": \\"0.3\\"}, {\\"ticker\\": \\"GOOGL\\", \\"weight\\": \\"0.2\\"}]}"
      }'
```
Lambda responses include the encoded body in the `body` property; decode it to inspect the JSON payload.

## Running Tests
- With uv: `make unit-tests`
- With an activated virtualenv: `pytest`

## Docker
- Build the runtime image: `docker build -t custom-basket .`
- Run unit tests in the container: `docker build --target unit-tests .`
- Emulate Lambda locally: `docker run --rm -p 9000:8080 custom-basket`

## Observability
- `/metrics` returns Prometheus exposition format with `basket_pricing_requests_total` and `basket_pricing_duration_seconds`.
  Scrape it from FastAPI directly or via the container port.

## Notes
- The bundled market and FX data is illustrative only. Supply overrides in the request payload to price instruments outside the sample universe.
- Normalized weights are based on gross exposure; a warning is returned if the provided weights do not sum to one.

## Deployment
I chose IBM Cloud because BNP Paribas is supposed to use it (source: ChatGPT): 
```
# Pause the app (no auto-start on requests)
ibmcloud ce app pause --name custom-basket-api

# Later, if you want to resume:
ibmcloud ce app resume --name custom-basket-api
```
