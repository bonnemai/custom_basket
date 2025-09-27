from decimal import Decimal

import pytest

from app.models import BasketPositionRequest, BasketRequest, FxRate, MarketDataPoint
from app.services.market_data import MarketDataProvider
from app.services.pricing import FxRateProvider, PricingService


def _create_service() -> PricingService:
    return PricingService(MarketDataProvider(), FxRateProvider())


def test_price_basket_basic_notional() -> None:
    service = _create_service()

    request = BasketRequest(
        basket_name="Tech",
        base_currency="USD",
        positions=[
            BasketPositionRequest(ticker="AAPL", weight=Decimal("0.5")),
            BasketPositionRequest(ticker="MSFT", weight=Decimal("0.3")),
            BasketPositionRequest(ticker="GOOGL", weight=Decimal("0.2")),
        ],
        notional=Decimal("1000000"),
    )

    result = service.price_basket(request)

    assert result.basket_price == Decimal("224.4530")
    assert result.total_notional == Decimal("1000000")
    assert len(result.positions) == 3
    aapl = result.positions[0]
    assert aapl.ticker == "AAPL"
    assert aapl.position_notional == Decimal("500000.00")
    assert aapl.quantity == Decimal("2637.9656")


def test_price_with_market_data_and_fx_overrides() -> None:
    service = _create_service()

    request = BasketRequest(
        basket_name="CrossCurrency",
        base_currency="USD",
        positions=[
            BasketPositionRequest(ticker="AAPL", weight=Decimal("0.6")),
            BasketPositionRequest(ticker="SAP", weight=Decimal("0.4")),
        ],
        market_data=[
            MarketDataPoint(ticker="SAP", price=Decimal("125"), currency="EUR"),
        ],
        fx_rates=[
            FxRate(base_currency="EUR", quote_currency="USD", rate=Decimal("1.10")),
        ],
    )

    result = service.price_basket(request)

    # 0.6 * 189.54 + 0.4 * (125 * 1.10) = 113.724 + 55 = 168.724
    assert result.basket_price == Decimal("168.7240")
    sap = next(pos for pos in result.positions if pos.ticker == "SAP")
    assert sap.price_currency == "EUR"
    assert sap.fx_rate_to_base == Decimal("1.10")
    assert sap.price_in_base == Decimal("137.5000")


def test_weights_normalization_message() -> None:
    service = _create_service()

    request = BasketRequest(
        basket_name="Overweight",
        base_currency="USD",
        positions=[
            BasketPositionRequest(ticker="AAPL", weight=Decimal("0.6")),
            BasketPositionRequest(ticker="MSFT", weight=Decimal("0.6")),
        ],
    )

    result = service.price_basket(request)

    assert any("do not sum to 1" in message for message in result.messages)
    assert result.weight_sum == Decimal("1.2")


def test_raises_when_missing_market_data() -> None:
    service = _create_service()

    request = BasketRequest(
        basket_name="Unknown",
        base_currency="USD",
        positions=[
            BasketPositionRequest(ticker="XYZ", weight=Decimal("1")),
        ],
    )

    with pytest.raises(KeyError):
        service.price_basket(request)
