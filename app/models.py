"""Pydantic data models for the basket pricing service."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator
from pydantic.functional_serializers import PlainSerializer

DecimalNumber = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]


class MarketDataPoint(BaseModel):
    """Represents a single spot price for an instrument."""

    ticker: str = Field(..., description="Instrument identifier")
    price: DecimalNumber = Field(..., gt=0, description="Spot price in the quote currency")
    currency: str = Field("USD", min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()


class FxRate(BaseModel):
    """Foreign exchange rate definition."""

    base_currency: str = Field(..., min_length=3, max_length=3)
    quote_currency: str = Field(..., min_length=3, max_length=3)
    rate: DecimalNumber = Field(..., gt=0)

    @field_validator("base_currency", "quote_currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()


class BasketPositionRequest(BaseModel):
    """Definition of a single basket constituent."""

    ticker: str = Field(..., description="Instrument identifier")
    weight: DecimalNumber = Field(..., description="Relative weight of the constituent")
    price: DecimalNumber | None = Field(
        default=None,
        gt=0,
        description="Override price for the instrument in the provided currency",
    )
    currency: str = Field(
        default="USD",
        description="Currency of the override price (defaults to USD)",
        min_length=3,
        max_length=3,
    )
    metadata: Optional[Dict[str, str]] = Field(
        default=None,
        description="Optional bag for client supplied metadata",
    )

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("weight")
    @classmethod
    def validate_weight(cls, value: Decimal) -> Decimal:
        if value == 0:
            raise ValueError("weight must be non-zero")
        return value


class BasketRequest(BaseModel):
    """Payload accepted by the pricing endpoint."""

    basket_name: str = Field(..., description="Client facing basket identifier")
    base_currency: str = Field("USD", min_length=3, max_length=3)
    positions: List[BasketPositionRequest] = Field(..., min_length=1)
    notional: DecimalNumber | None = Field(
        default=None,
        gt=0,
        description="Optional target notional for the basket in base currency",
    )
    market_data: Optional[List[MarketDataPoint]] = Field(
        default=None,
        description="Inline market data overrides",
    )
    fx_rates: Optional[List[FxRate]] = Field(
        default=None,
        description="Inline FX rates to complement the default set",
    )

    @field_validator("base_currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()


class BasketPositionBreakdown(BaseModel):
    """Evaluation outcome for a single constituent."""

    ticker: str
    weight: DecimalNumber
    normalized_weight: DecimalNumber | None = None
    price: DecimalNumber
    price_currency: str
    price_in_base: DecimalNumber
    fx_rate_to_base: DecimalNumber
    contribution: DecimalNumber
    position_notional: DecimalNumber | None = None
    quantity: DecimalNumber | None = None
    currency: str


class BasketPricingResponse(BaseModel):
    """Response returned to clients after pricing."""

    basket_name: str
    base_currency: str
    weight_sum: DecimalNumber
    basket_price: DecimalNumber
    total_notional: DecimalNumber | None = None
    positions: List[BasketPositionBreakdown]
    messages: List[str] = Field(default_factory=list)
