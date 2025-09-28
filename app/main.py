"""Application entry point for the FastAPI basket pricing service."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sse_starlette.sse import EventSourceResponse

from .models import BasketPricingResponse, BasketRequest, BasketState, BasketStreamPayload
from .services.basket_cache import BasketCache, CachedBasket
from .services.market_data import MarketDataProvider
from .services.pricing import FxRateProvider, PricingService
from .services.spot_providers import SpotProvider


logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Application factory to allow testability."""

    app = FastAPI(
        title="Delta-One Custom Basket Pricing API",
        version="0.2.0",
        description="Compute indicative prices and exposures for bespoke baskets.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    market_data_provider = MarketDataProvider()
    fx_provider = FxRateProvider()
    pricing_service = PricingService(market_data_provider, fx_provider)
    basket_cache = BasketCache()
    eodhd_token = os.getenv("EODHD_API_TOKEN")
    spot_provider = SpotProvider(market_data_provider, api_token=eodhd_token)

    try:
        stream_interval = float(os.getenv("BASKET_STREAM_INTERVAL", "1"))
    except ValueError:  # pragma: no cover - defensive parsing
        stream_interval = 5.0
    stream_interval = max(stream_interval, 0.1)

    async def shutdown_event() -> None:
        await spot_provider.aclose()

    app.add_event_handler("shutdown", shutdown_event)

    def initialize_seed_basket() -> None:
        seed_payload = {
            "basket_name": "Seed Basket",
            "base_currency": "USD",
            "positions": [
                {"ticker": "AAPL", "weight": "0.5"},
                {"ticker": "MSFT", "weight": "0.3"},
                {"ticker": "GOOGL", "weight": "0.2"},
            ],
            "notional": "1000000",
        }
        try:
            request_model = BasketRequest.model_validate(seed_payload)
            pricing = pricing_service.price_basket(request_model)
            basket_cache.upsert("seed-basket", request_model, pricing)
            logger.info("Seed basket initialised in cache")
        except Exception as exc:  # pragma: no cover - bootstrap safety
            logger.warning("Unable to initialise seed basket: %s", exc)

    def price_request(request: BasketRequest) -> BasketPricingResponse:
        try:
            return pricing_service.price_basket(request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def to_state(entity: CachedBasket) -> BasketState:
        payload = entity.pricing.model_dump()
        return BasketState(
            **payload,
            basket_id=entity.basket_id,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    def collect_tickers(baskets: Iterable[CachedBasket]) -> set[str]:
        symbols: set[str] = set()
        for basket in baskets:
            for position in basket.definition.positions:
                symbols.add(position.ticker.upper())
        return symbols

    @app.post("/baskets", response_model=BasketState, status_code=201)
    def create_basket(request: BasketRequest) -> BasketState:
        basket_id = uuid4().hex
        pricing = price_request(request)
        cached = basket_cache.upsert(basket_id, request, pricing)
        return to_state(cached)

    @app.put("/baskets/{basket_id}", response_model=BasketState)
    def replace_basket(basket_id: str, request: BasketRequest) -> BasketState:
        if basket_cache.get(basket_id) is None:
            raise HTTPException(status_code=404, detail=f"Basket {basket_id} not found")
        pricing = price_request(request)
        cached = basket_cache.upsert(basket_id, request, pricing)
        return to_state(cached)

    @app.patch("/baskets/{basket_id}", response_model=BasketState)
    def patch_basket(basket_id: str, request: BasketRequest) -> BasketState:
        return replace_basket(basket_id, request)

    @app.get("/baskets", response_model=list[BasketState])
    def list_baskets() -> list[BasketState]:
        return [to_state(item) for item in basket_cache.list()]

    @app.post("/pricing/basket", response_model=BasketPricingResponse)
    def post_basket_price(request: BasketRequest) -> BasketPricingResponse:
        return price_request(request)

    @app.get("/market-data/{ticker}")
    def get_market_quote(ticker: str) -> dict:
        try:
            quote = market_data_provider.get_quote(ticker)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "ticker": ticker.upper(),
            "price": float(quote.price),
            "currency": quote.currency,
        }

    index_html = (Path(__file__).resolve().parent / "templates" / "index.html").read_text(encoding="utf-8")

    @app.get("/", response_class=HTMLResponse)
    def get_index() -> HTMLResponse:
        return HTMLResponse(index_html)

    @app.get("/metrics")
    def get_metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    async def stream_generator():
        try:
            while True:
                snapshot = basket_cache.list()
                tickers = collect_tickers(snapshot)

                if not snapshot or not tickers:
                    payload = BasketStreamPayload(
                        as_of=datetime.now(timezone.utc),
                        baskets=[],
                    )
                    yield {
                        "event": "heartbeat",
                        "data": payload.model_dump_json(),
                    }
                    await asyncio.sleep(stream_interval)
                    continue

                quotes = await spot_provider.get_quotes(tickers)
                updates: list[BasketState] = []

                for basket in snapshot:
                    overrides_map = {
                        position.ticker.upper(): quotes[position.ticker.upper()]
                        for position in basket.definition.positions
                        if position.ticker.upper() in quotes
                    }

                    try:
                        pricing = pricing_service.price_basket(
                            basket.definition,
                            market_overrides=overrides_map,
                        )
                    except Exception as exc:  # pragma: no cover - defensive logging
                        logger.warning("Failed to refresh basket %s: %s", basket.basket_id, exc)
                        continue

                    basket_cache.update_pricing(basket.basket_id, pricing)
                    refreshed = basket_cache.get(basket.basket_id)
                    if refreshed is not None:
                        updates.append(to_state(refreshed))

                payload = BasketStreamPayload(
                    as_of=datetime.now(timezone.utc),
                    baskets=updates,
                )
                yield {
                    "event": "prices",
                    "data": payload.model_dump_json(),
                }

                await asyncio.sleep(stream_interval)
        except asyncio.CancelledError:  # pragma: no cover - triggered on disconnect
            logger.debug("Basket SSE client disconnected")
            raise

    @app.get("/baskets/stream")
    async def stream_basket_prices() -> EventSourceResponse:
        response = EventSourceResponse(stream_generator())
        # Disable default ping to avoid deprecated datetime.utcnow usage in dependency.
        if hasattr(response, "ping_interval"):
            response.ping_interval = 1_000  # type: ignore[attr-defined]
        if hasattr(response, "_ping_task") and response._ping_task:  # type: ignore[attr-defined]
            response._ping_task.cancel()  # pragma: no cover - defensive safety
        return response

    initialize_seed_basket()

    return app


app = create_app()
