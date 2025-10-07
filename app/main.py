"""Application entry point for the FastAPI basket pricing service."""

from __future__ import annotations

import asyncio
import logging
import os
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from mangum import Mangum
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .models import BasketPricingResponse, BasketRequest, BasketState, BasketStreamPayload
from .services.basket_cache import BasketCache, CachedBasket
from .services.market_data import MarketDataProvider
from .services.pricing import FxRateProvider, PricingService
from .services.spot_providers import SpotProvider


logger = logging.getLogger(__name__)


@dataclass
class AppResources:
    market_data_provider: MarketDataProvider
    fx_provider: FxRateProvider
    pricing_service: PricingService
    basket_cache: BasketCache
    spot_provider: SpotProvider
    stream_interval: float
    index_template: str


allow_origins = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if o.strip()]
def configure_cors(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def parse_stream_interval(raw_value: str | None) -> float:
    if raw_value is None:
        return 1.0
    try:
        parsed = float(raw_value)
    except ValueError:  # pragma: no cover - defensive parsing
        parsed = 5.0
    return max(parsed, 0.1)


def build_app_resources() -> AppResources:
    market_data_provider = MarketDataProvider()
    fx_provider = FxRateProvider()
    pricing_service = PricingService(market_data_provider, fx_provider)
    basket_cache = BasketCache()
    eodhd_token = os.getenv("EODHD_API_TOKEN")
    spot_provider = SpotProvider(api_token=eodhd_token)
    stream_interval = parse_stream_interval(os.getenv("BASKET_STREAM_INTERVAL"))
    index_template = (Path(__file__).resolve().parent / "templates" / "index.html").read_text(encoding="utf-8")
    return AppResources(
        market_data_provider=market_data_provider,
        fx_provider=fx_provider,
        pricing_service=pricing_service,
        basket_cache=basket_cache,
        spot_provider=spot_provider,
        stream_interval=stream_interval,
        index_template=index_template,
    )


def add_shutdown_handler(app: FastAPI, spot_provider: SpotProvider) -> None:
    async def shutdown_event() -> None:
        await spot_provider.aclose()

    app.add_event_handler("shutdown", shutdown_event)


def initialize_seed_basket(resources: AppResources) -> None:
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
        pricing = resources.pricing_service.price_basket(request_model)
        resources.basket_cache.upsert("seed-basket", request_model, pricing)
        logger.info("Seed basket initialised in cache")
    except Exception as exc:  # pragma: no cover - bootstrap safety
        logger.warning("Unable to initialise seed basket: %s", exc)


def to_state(entity: CachedBasket) -> BasketState:
    payload = entity.pricing.model_dump()
    return BasketState(
        **payload,
        basket_id=entity.basket_id,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def apply_random_spot_variation(state: BasketState) -> BasketState:
    """Apply random variation to spot prices: spot * (1 + 0.1 * (dice - 0.5))"""
    from decimal import Decimal

    # Create a copy of the state with varied prices
    varied_positions = []
    basket_price = Decimal("0")

    for position in state.positions:
        dice = random.random()  # Random float between 0 and 1
        variation_factor = Decimal(str(1 + 0.1 * (dice - 0.5)))

        # Apply variation to the spot price
        varied_price = position.price * variation_factor
        varied_price_in_base = position.price_in_base * variation_factor
        varied_contribution = position.weight * varied_price_in_base

        # Update basket price
        basket_price += varied_contribution

        # Calculate varied position notional and quantity if applicable
        varied_position_notional = None
        varied_quantity = None
        if position.position_notional is not None and position.normalized_weight is not None:
            varied_position_notional = state.total_notional * position.normalized_weight if state.total_notional else None
            if varied_position_notional and varied_price_in_base != 0:
                varied_quantity = varied_position_notional / varied_price_in_base

        # Create varied position
        varied_positions.append(
            position.model_copy(
                update={
                    "price": varied_price,
                    "price_in_base": varied_price_in_base,
                    "contribution": varied_contribution,
                    "position_notional": varied_position_notional,
                    "quantity": varied_quantity,
                }
            )
        )

    # Return updated state with varied prices
    return state.model_copy(
        update={
            "basket_price": basket_price,
            "positions": varied_positions,
        }
    )


def collect_tickers(baskets: Iterable[CachedBasket]) -> set[str]:
    symbols: set[str] = set()
    for basket in baskets:
        for position in basket.definition.positions:
            symbols.add(position.ticker.upper())
    return symbols


def make_price_request(pricing_service: PricingService):
    def price_request(request: BasketRequest) -> BasketPricingResponse:
        try:
            return pricing_service.price_basket(request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return price_request


def heartbeat_event() -> dict:
    payload = BasketStreamPayload(
        as_of=datetime.now(timezone.utc),
        baskets=[],
    )
    return {"event": "heartbeat", "data": payload.model_dump_json()}


def build_overrides_map(basket: CachedBasket, quotes: dict[str, float]) -> dict[str, float]:
    return {
        position.ticker.upper(): quotes[position.ticker.upper()]
        for position in basket.definition.positions
        if position.ticker.upper() in quotes
    }


def refresh_baskets(
    snapshot: Iterable[CachedBasket],
    quotes: dict[str, float],
    basket_cache: BasketCache,
    pricing_service: PricingService,
) -> list[BasketState]:
    updates: list[BasketState] = []
    for basket in snapshot:
        overrides_map = build_overrides_map(basket, quotes)
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
    return updates


def prices_event(updates: list[BasketState]) -> dict:
    payload = BasketStreamPayload(
        as_of=datetime.now(timezone.utc),
        baskets=updates,
    )
    return {"event": "prices", "data": payload.model_dump_json()}


async def stream_basket_events(
    basket_cache: BasketCache,
    spot_provider: SpotProvider,
    pricing_service: PricingService,
    stream_interval: float,
) -> Iterable[dict]:
    try:
        while True:
            snapshot = basket_cache.list()
            tickers = collect_tickers(snapshot)
            if not snapshot or not tickers:
                yield heartbeat_event()
                await asyncio.sleep(stream_interval)
                continue

            quotes = await spot_provider.get_quotes(tickers)
            updates = refresh_baskets(snapshot, quotes, basket_cache, pricing_service)
            yield prices_event(updates)
            await asyncio.sleep(stream_interval)
    except asyncio.CancelledError:  # pragma: no cover - triggered on disconnect
        logger.debug("Basket SSE client disconnected")
        raise


def register_routes(app: FastAPI, resources: AppResources) -> None:
    basket_cache = resources.basket_cache
    pricing_service = resources.pricing_service
    market_data_provider = resources.market_data_provider
    spot_provider = resources.spot_provider
    stream_interval = resources.stream_interval
    index_template = resources.index_template
    price_request = make_price_request(pricing_service)

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
        return [apply_random_spot_variation(to_state(item)) for item in basket_cache.list()]

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

    @app.get("/", response_class=HTMLResponse)
    def get_index() -> HTMLResponse:
        token = os.getenv("EODHD_API_TOKEN") or ""
        token_prefix = token[:5] if token else "(unset)"
        content = index_template.replace("{{TOKEN_PREFIX}}", token_prefix)
        return HTMLResponse(content)

    @app.get("/metrics")
    def get_metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/baskets/stream")
    async def stream() -> StreamingResponse:
        async def sse_gen():
            async for event in stream_basket_events(
                basket_cache=basket_cache,
                spot_provider=spot_provider,
                pricing_service=pricing_service,
                stream_interval=stream_interval,
            ):
                event_name = event.get("event")
                data = event.get("data") or ""
                if event_name:
                    yield f"event: {event_name}\n"
                yield f"data: {data}\n\n"

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
        return StreamingResponse(sse_gen(), media_type="text/event-stream", headers=headers)


def create_app() -> FastAPI:
    """Application factory to allow testability."""

    app = FastAPI(
        title="Delta-One Custom Basket Pricing API",
        version="0.0.0",
        description="Compute indicative prices and exposures for bespoke baskets.",
    )

    configure_cors(app)
    resources = build_app_resources()
    add_shutdown_handler(app, resources.spot_provider)
    register_routes(app, resources)
    initialize_seed_basket(resources)

    return app


app = create_app()
lambda_handler = Mangum(app)
