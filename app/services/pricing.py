"""Core pricing logic for the basket service."""

from __future__ import annotations

import time

from decimal import Decimal, ROUND_HALF_UP, getcontext
from typing import Dict, Iterable, Mapping, Tuple

from prometheus_client import Counter, Histogram

from ..models import (
    BasketPositionBreakdown,
    BasketRequest,
    BasketPricingResponse,
    FxRate,
)
from .market_data import MarketDataProvider, MarketQuote

# Higher precision during intermediate calculations
getcontext().prec = 28


PRICING_REQUESTS = Counter(
    "basket_pricing_requests_total",
    "Total number of basket pricing requests processed",
    ["status"],
)

PRICING_DURATION = Histogram(
    "basket_pricing_duration_seconds",
    "Time taken to price a basket",
)


class FxRateProvider:
    """In-memory FX rate provider with override support."""

    def __init__(self, rates: Mapping[Tuple[str, str], Decimal] | None = None) -> None:
        self._rates: Dict[Tuple[str, str], Decimal] = {
            ("USD", "EUR"): Decimal("0.92"),
            ("EUR", "USD"): Decimal("1.087"),
            ("USD", "GBP"): Decimal("0.78"),
            ("GBP", "USD"): Decimal("1.28"),
            ("USD", "JPY"): Decimal("140.0"),
            ("JPY", "USD"): Decimal("0.00714"),
        }
        if rates:
            for (base, quote), rate in rates.items():
                self._rates[(base.upper(), quote.upper())] = rate

    def snapshot(self) -> Dict[Tuple[str, str], Decimal]:
        return dict(self._rates)

    @staticmethod
    def build_overrides(data_points: Iterable[FxRate] | None) -> Dict[Tuple[str, str], Decimal]:
        if not data_points:
            return {}
        overrides: Dict[Tuple[str, str], Decimal] = {}
        for item in data_points:
            overrides[(item.base_currency, item.quote_currency)] = item.rate
        return overrides

    def get_rate(
        self,
        from_currency: str,
        to_currency: str,
        overrides: Mapping[Tuple[str, str], Decimal] | None = None,
    ) -> Decimal:
        base = from_currency.upper()
        quote = to_currency.upper()
        if base == quote:
            return Decimal("1")
        if overrides and (base, quote) in overrides:
            return overrides[(base, quote)]
        if (base, quote) in self._rates:
            return self._rates[(base, quote)]
        # Attempt inverse
        inverse_key = (quote, base)
        if overrides and inverse_key in overrides:
            return Decimal("1") / overrides[inverse_key]
        if inverse_key in self._rates:
            return Decimal("1") / self._rates[inverse_key]
        raise KeyError(f"No FX rate available for {base}/{quote}")


class PricingService:
    """Compute price and exposures for a delta-one basket."""

    def __init__(
        self,
        market_data_provider: MarketDataProvider,
        fx_provider: FxRateProvider,
    ) -> None:
        self._market_data_provider = market_data_provider
        self._fx_provider = fx_provider

    def price_basket(self, request: BasketRequest) -> BasketPricingResponse:
        start_time = time.perf_counter()
        status = "success"
        try:
            market_overrides = self._market_data_provider.build_overrides(request.market_data)
            fx_overrides = self._fx_provider.build_overrides(request.fx_rates)

            weight_sum = Decimal("0")
            gross_weight = Decimal("0")
            for position in request.positions:
                weight_sum += position.weight
                gross_weight += abs(position.weight)

            messages = []
            weight_normalization_available = gross_weight != 0
            if not weight_normalization_available:
                raise ValueError("The basket contains only zero weights; cannot compute price.")
            if abs(weight_sum - Decimal("1")) > Decimal("0.0001"):
                messages.append(
                    "Position weights do not sum to 1. Normalized weights are based on the gross exposure."
                )

            basket_price = Decimal("0")
            breakdown: list[BasketPositionBreakdown] = []

            for position in request.positions:
                quote = self._resolve_quote(position.ticker, market_overrides, position)
                fx_rate = self._fx_provider.get_rate(quote.currency, request.base_currency, fx_overrides)
                price_in_base_raw = quote.price * fx_rate
                price_in_base = price_in_base_raw.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

                raw_contribution = position.weight * price_in_base_raw
                basket_price += raw_contribution

                normalized_weight = None
                if gross_weight != 0:
                    normalized_weight = (position.weight / gross_weight).quantize(
                        Decimal("0.0000001"), rounding=ROUND_HALF_UP
                    )

                position_notional = None
                quantity = None
                if request.notional is not None and normalized_weight is not None:
                    position_notional = (request.notional * normalized_weight).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    if price_in_base_raw != 0:
                        quantity = (position_notional / price_in_base_raw).quantize(
                            Decimal("0.0001"), rounding=ROUND_HALF_UP
                        )

                breakdown.append(
                    BasketPositionBreakdown(
                        ticker=position.ticker,
                        weight=position.weight,
                        normalized_weight=normalized_weight,
                        price=quote.price,
                        price_currency=quote.currency,
                        price_in_base=price_in_base,
                        fx_rate_to_base=fx_rate,
                        contribution=raw_contribution.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
                        position_notional=position_notional,
                        quantity=quantity,
                        currency=quote.currency,
                    )
                )

            basket_price = basket_price.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

            return BasketPricingResponse(
                basket_name=request.basket_name,
                base_currency=request.base_currency,
                weight_sum=weight_sum,
                basket_price=basket_price,
                total_notional=request.notional,
                positions=breakdown,
                messages=messages,
            )
        except KeyError:
            status = "missing_market_data"
            raise
        except ValueError:
            status = "invalid_request"
            raise
        except Exception:
            status = "error"
            raise
        finally:
            duration = time.perf_counter() - start_time
            PRICING_DURATION.observe(duration)
            PRICING_REQUESTS.labels(status=status).inc()

    def _resolve_quote(
        self,
        ticker: str,
        overrides: Mapping[str, MarketQuote],
        position,
    ) -> MarketQuote:
        if position.price is not None:
            return MarketQuote(price=position.price, currency=position.currency)
        if overrides and ticker.upper() in overrides:
            return overrides[ticker.upper()]
        return self._market_data_provider.get_quote(ticker, overrides)
