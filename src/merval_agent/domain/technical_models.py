from datetime import date, datetime
from typing import Literal

from pydantic import Field

from .model_base import HistoryRange, Model


class TechnicalMetrics(Model):
    current_price: float | None = Field(default=None, gt=0)
    macd_histogram: float | None = None
    previous_macd_histogram: float | None = None
    sma20: float | None = None
    sma50: float | None = None
    ema12: float | None = None
    ema26: float | None = None
    rsi14: float | None = Field(default=None, ge=0, le=100)
    macd: float | None = None
    macd_signal: float | None = None
    change_percent: float | None = None
    period_high: float | None = None
    period_low: float | None = None
    average_volume: float | None = None
    sample_size: int = Field(default=0, ge=0)


Signal = Literal["BULLISH", "BEARISH", "NEUTRAL", "MIXED", "UNAVAILABLE"]


class TechnicalSignal(Model):
    signal: Signal
    explanation: str


class IndicatorBasis(Model):
    resolved_variant: str | None = None
    range: HistoryRange | None = None
    history_as_of: date | None = None
    indicators_as_of: date | None = None
    history_fetched_at: datetime | None = None
    history_provider_fetched_at: datetime | None = None
    history_received_at: datetime | None = None
    history_provider_clock_skew_ms: float | None = None
    history_closure: Literal["UNVERIFIED"] = "UNVERIFIED"
    quote_as_of: date | None = None
    quote_observed_at: datetime | None = None
    quote_fetched_at: datetime | None = None
    quote_provider_fetched_at: datetime | None = None
    quote_received_at: datetime | None = None
    quote_provider_clock_skew_ms: float | None = None
    quote_price: float | None = None
    quote_provisional: bool = False
    quote_in_indicators: bool = False
    policy: Literal["HISTORY_ONLY", "INCLUDE_PROVISIONAL_OHLC"] = "HISTORY_ONLY"


class TechnicalAssessment(Model):
    status: Literal[
        "COMPLETE",
        "PARTIAL",
        "INSUFFICIENT_DATA",
        "SOURCE_ERROR",
        "STALE",
        "INVALID_DATA",
        "UNVERIFIED",
    ]
    signals: dict[str, TechnicalSignal] = Field(default_factory=dict)
    trend: Signal = "UNAVAILABLE"
    momentum: Signal = "UNAVAILABLE"
    momentum_state: Literal[
        "BULLISH",
        "BEARISH",
        "NEUTRAL",
        "MIXED",
        "UNAVAILABLE",
        "IMPROVING_BUT_BEARISH",
        "WEAKENING_BUT_BULLISH",
        "RECOVERY_FADING_BUT_BEARISH",
    ] = "UNAVAILABLE"
    confirmation: Literal["ALIGNED", "UNCONFIRMED", "UNAVAILABLE"] = "UNAVAILABLE"
    volume_confirmation: Literal["CONFIRMED", "NOT_CONFIRMED", "UNAVAILABLE"] = "UNAVAILABLE"
    volume_as_of: date | None = None
    completion_reasons: list[str] = Field(default_factory=list)
    basis: IndicatorBasis = Field(default_factory=IndicatorBasis)
    conclusion: Signal = "UNAVAILABLE"
    confidence: Literal["HIGH", "MEDIUM", "LOW", "UNAVAILABLE"] = "UNAVAILABLE"
    as_of: date | None = None
    fetched_at: datetime | None = None
    provider_fetched_at: datetime | None = None
    received_at: datetime | None = None
    freshness: Literal["RECENT", "STALE", "INVALID", "UNKNOWN"] = "UNKNOWN"
    missing_indicators: dict[str, str] = Field(default_factory=dict)
    agreements: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
