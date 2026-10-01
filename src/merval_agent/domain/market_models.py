from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from .model_base import CalendarDate, HistoryRange, Model, Ticker


class CompanyType(StrEnum):
    INDUSTRIAL = "INDUSTRIAL"
    ENERGY = "ENERGY"
    UTILITY = "UTILITY"
    FINANCIAL = "FINANCIAL"
    OTHER = "OTHER"


class AssetResolution(Model):
    status: Literal["RESOLVED", "AMBIGUOUS", "NOT_FOUND", "UNSUPPORTED"] = "NOT_FOUND"
    ticker: Ticker | None = None
    company_name: str | None = None
    company_type: CompanyType = CompanyType.OTHER
    market: Literal["bCBA"] | None = None
    confidence: float = Field(ge=0, le=1)
    alternatives: list[str] = Field(default_factory=list)
    requested_symbol: str | None = Field(default=None, max_length=30, pattern=r"^[A-Z0-9._-]+$")
    validation_method: Literal["catalog", "provider_quote", "none"] = "none"
    validation_status: Literal[
        "VALIDATED",
        "NOT_FOUND",
        "UNSUPPORTED",
        "AMBIGUOUS",
        "INVALID_FORMAT",
        "NOT_ATTEMPTED",
    ] = "NOT_ATTEMPTED"
    validation_source: str | None = None
    existence_status: Literal["CONFIRMED", "NOT_FOUND", "NOT_VERIFIED"] = "NOT_VERIFIED"
    eligibility_status: Literal["ELIGIBLE", "UNSUPPORTED", "NOT_EVALUATED"] = "NOT_EVALUATED"
    eligibility_reason: (
        Literal["DOMESTIC_EQUITY", "CEDEAR", "FOREIGN_MARKET", "OTHER_INSTRUMENT"] | None
    ) = None
    eligibility_method: Literal[
        "catalog_metadata", "provider_description_policy", "request_market", "none"
    ] = "none"

    @model_validator(mode="before")
    @classmethod
    def infer_legacy_status(cls, value):
        if isinstance(value, dict) and "status" not in value:
            value = dict(value)
            value["status"] = (
                "RESOLVED"
                if value.get("ticker")
                else "AMBIGUOUS"
                if value.get("alternatives")
                else "NOT_FOUND"
            )
        return value

    @model_validator(mode="after")
    def valid_resolution(self):
        if self.status in ("RESOLVED", "UNSUPPORTED") and self.ticker is None:
            raise ValueError("Identified asset requires ticker")
        if self.status in ("AMBIGUOUS", "NOT_FOUND") and self.ticker is not None:
            raise ValueError("Unresolved asset cannot expose ticker")
        if self.status == "AMBIGUOUS" and not self.alternatives:
            raise ValueError("AMBIGUOUS asset requires alternatives")
        return self


class ErrorInfo(Model):
    code: str
    message: str
    retryable: bool = False


class Bar(Model):
    date: CalendarDate
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float | None = Field(ge=0)

    @model_validator(mode="after")
    def valid_prices(self):
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("Inconsistent OHLC")
        return self


DiscardedHistoryReason = Literal[
    "CLOSE_ABOVE_HIGH",
    "CLOSE_BELOW_LOW",
    "OPEN_ABOVE_HIGH",
    "OPEN_BELOW_LOW",
    "HIGH_BELOW_LOW",
    "INVALID_PRICE",
    "INVALID_VOLUME",
    "MALFORMED_ROW",
    "VALIDATION_ERROR",
]


class DiscardedHistoryRow(Model):
    """Bounded audit evidence for one rejected upstream history row."""

    index: int = Field(ge=0)
    date: CalendarDate | None = None
    open: int | float | str | bool | None = None
    high: int | float | str | bool | None = None
    low: int | float | str | bool | None = None
    close: int | float | str | bool | None = None
    volume: int | float | str | bool | None = None
    reason: DiscardedHistoryReason
    validation_error: str = Field(min_length=1, max_length=500)


class QuoteSnapshot(Model):
    bar: Bar
    source: str
    observed_at: datetime
    provider_fetched_at: datetime | None = None
    received_at: datetime
    currency: str = Field(min_length=1)
    mode: Literal["live"] = "live"
    provisional: Literal[True] = True

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_fetched_at(cls, value):
        if isinstance(value, dict) and "fetched_at" in value:
            value = dict(value)
            legacy = value.pop("fetched_at")
            value.setdefault("received_at", legacy)
        return value

    @model_validator(mode="after")
    def aware(self):
        if self.observed_at.tzinfo is None or self.received_at.tzinfo is None:
            raise ValueError("Quote timestamps require timezone")
        if self.provider_fetched_at and self.provider_fetched_at.tzinfo is None:
            raise ValueError("Provider quote timestamp requires timezone")
        return self

    @property
    def fetched_at(self) -> datetime:
        """Backward-compatible accessor; quote fetched_at always meant local receipt."""
        return self.received_at


class MarketHistory(Model):
    resolved_variant: str | None = None
    ticker: Ticker
    range: HistoryRange
    bars: list[Bar]
    source: str
    provider_fetched_at: datetime
    received_at: datetime
    mode: Literal["live", "demo", "unknown"] = "unknown"
    stale: bool = False
    currency: str | None = None
    quote: QuoteSnapshot | None = None
    discarded_rows: int = Field(default=0, ge=0)
    discarded_details: list[DiscardedHistoryRow] = Field(default_factory=list)
    enrichment_status: Literal[
        "not_requested", "appended", "excluded", "not_newer", "unavailable", "ineligible_history"
    ] = "not_requested"

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_fetched_at(cls, value):
        if isinstance(value, dict) and "fetched_at" in value:
            value = dict(value)
            legacy = value.pop("fetched_at")
            value.setdefault("provider_fetched_at", legacy)
            value.setdefault("received_at", legacy)
        return value

    @model_validator(mode="after")
    def ordered(self):
        dates = [b.date for b in self.bars]
        if dates != sorted(set(dates)):
            raise ValueError("Bars must be unique and chronological")
        if self.provider_fetched_at.tzinfo is None or self.received_at.tzinfo is None:
            raise ValueError("History timestamps require timezone")
        if (self.quote is not None) != (self.enrichment_status in ("appended", "excluded")):
            raise ValueError("Appended enrichment requires quote provenance")
        if self.discarded_details and self.discarded_rows != len(self.discarded_details):
            raise ValueError("Discarded row count must match available audit details")
        if (
            self.quote
            and self.enrichment_status == "appended"
            and (
                len(self.bars) < 2
                or self.bars[-1] != self.quote.bar
                or self.currency != self.quote.currency
            )
        ):
            raise ValueError("Quote must describe the last bar in the same currency")
        if (
            self.quote
            and self.enrichment_status == "excluded"
            and (
                not self.bars
                or self.quote.bar.date <= self.bars[-1].date
                or self.currency != self.quote.currency
            )
        ):
            raise ValueError("Excluded quote must be newer and in the same currency")
        return self

    @property
    def fetched_at(self) -> datetime:
        """Backward-compatible accessor for the former upstream fetched_at field."""
        return self.provider_fetched_at
