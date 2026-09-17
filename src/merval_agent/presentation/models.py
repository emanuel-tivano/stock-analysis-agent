from datetime import date
from typing import Literal

from pydantic import Field

from merval_agent.domain.models import Model


class PresentedValue(Model):
    code: str
    label: str
    short_label: str | None = None


class PresentedMetric(Model):
    key: str
    label: str
    value: float | int | None = None
    display: str
    summary: str | None = None


class PresentedExplanation(Model):
    label: str
    text: str


class PresentedSource(Model):
    url: str
    data_date: date | None = None
    provisional: bool = False


class TechnicalDetails(Model):
    trend: PresentedValue
    momentum: PresentedValue
    momentum_state: PresentedValue
    confirmation: PresentedValue
    confidence: PresentedValue
    sample_size: int | None = None
    sample_size_display: str = "No disponible"
    missing_indicators: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    signal_explanations: list[PresentedExplanation] = Field(default_factory=list)
    trace_id: str


class ChatResponse(Model):
    status: Literal["ANSWER", "CLARIFY", "ABSTAIN", "ERROR"]
    result_type: Literal[
        "successful_analysis",
        "asset_not_found",
        "ambiguous_asset",
        "insufficient_market_data",
        "other",
    ]
    ticker: str | None = None
    company_name: str | None = None
    heading: str
    user_message: str | None = None
    executive_summary: str
    conclusion: PresentedValue | None = None
    confidence: PresentedValue | None = None
    trend: PresentedValue | None = None
    momentum: PresentedValue | None = None
    momentum_state: PresentedValue | None = None
    rsi: PresentedMetric | None = None
    macd_summary: str | None = None
    indicators: list[PresentedMetric] = Field(default_factory=list)
    sources: list[PresentedSource] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    technical_details: TechnicalDetails | None = None
    trace_id: str
    session_id: str
