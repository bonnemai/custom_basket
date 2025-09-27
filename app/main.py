"""Application entry point for the FastAPI basket pricing service."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .models import BasketPricingResponse, BasketRequest
from .services.market_data import MarketDataProvider
from .services.pricing import FxRateProvider, PricingService


def create_app() -> FastAPI:
    """Application factory to allow testability."""

    app = FastAPI(
        title="Delta-One Custom Basket Pricing API",
        version="0.1.0",
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

    @app.post("/pricing/basket", response_model=BasketPricingResponse)
    def post_basket_price(request: BasketRequest) -> BasketPricingResponse:
        try:
            return pricing_service.price_basket(request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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

    @app.get("/metrics")
    def get_metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
