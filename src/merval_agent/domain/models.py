from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

Ticker = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z]{2,5}$"),
    BeforeValidator(lambda v: v.strip().upper() if isinstance(v, str) else v),
]
HistoryRange = Literal["1W", "1M", "3M", "6M", "1Y"]


def now() -> datetime:
    return datetime.now(UTC)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CompanyType(StrEnum):
    INDUSTRIAL = "INDUSTRIAL"
    ENERGY = "ENERGY"
    UTILITY = "UTILITY"
    FINANCIAL = "FINANCIAL"
    OTHER = "OTHER"


class UserIntent(Model):
    analysis_type: Literal["technical", "fundamental", "full"] = "full"
    methodology: list[Literal["murphy", "graham"]] = Field(default_factory=list)


class AssetResolution(Model):
    ticker: Ticker | None = None
    company_name: str | None = None
    company_type: CompanyType = CompanyType.OTHER
    confidence: float = Field(ge=0, le=1)
    alternatives: list[str] = Field(default_factory=list)


class ErrorInfo(Model):
    code: str
    message: str
    retryable: bool = False


class Bar(Model):
    date: date
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)

    @model_validator(mode="after")
    def valid_prices(self):
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("Inconsistent OHLC")
        return self


class MarketHistory(Model):
    ticker: Ticker
    range: HistoryRange
    bars: list[Bar]
    source: str
    fetched_at: datetime
    mode: Literal["live", "demo", "unknown"] = "unknown"
    stale: bool = False
    currency: str | None = None

    @model_validator(mode="after")
    def ordered(self):
        dates = [b.date for b in self.bars]
        if dates != sorted(set(dates)):
            raise ValueError("Bars must be unique and chronological")
        if self.fetched_at.tzinfo is None:
            raise ValueError("fetched_at requires timezone")
        return self


class TechnicalMetrics(Model):
    sma20: float | None = None
    sma50: float | None = None
    ema12: float | None = None
    ema26: float | None = None
    rsi14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    change_percent: float | None = None
    period_high: float | None = None
    period_low: float | None = None
    average_volume: float | None = None
    sample_size: int = 0


class FinancialDocument(Model):
    ticker: Ticker
    issuer: str
    published_at: date
    reference: str
    document_id: str
    source_url: str
    fiscal_period: str | None = None
    document_type: Literal["FINANCIAL_STATEMENT", "SUMMARY", "OTHER"]


class Evidence(Model):
    source: str
    chunk_id: str
    text: str
    score: float = Field(ge=0, le=1)
    kind: Literal["DATA", "METHODOLOGY", "DEMO"]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCall(Model):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    step_number: int = Field(default=0, ge=0)


class ToolResult(Model):
    tool_name: str
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: ErrorInfo | None = None
    latency_ms: float = 0


class AgentDecision(Model):
    action: Literal["CALL_TOOL", "CLARIFY", "FINAL_ANSWER", "ABSTAIN"]
    tool_name: str | None = None
    tool_args: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1)
    missing_information: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    intent: UserIntent | None = None
    interpretation: str = ""

    @model_validator(mode="after")
    def action_shape(self):
        if self.action == "CALL_TOOL" and not self.tool_name:
            raise ValueError("CALL_TOOL requires tool_name")
        if self.action != "CALL_TOOL" and (self.tool_name or self.tool_args):
            raise ValueError("Terminal action cannot call tools")
        return self


class Dimension(Model):
    status: Literal[
        "BULLISH",
        "BEARISH",
        "NEUTRAL",
        "POSITIVE",
        "MIXED",
        "NEGATIVE",
        "INSUFFICIENT_DATA",
        "NOT_REQUESTED",
    ] = "INSUFFICIENT_DATA"
    metrics: TechnicalMetrics | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    interpretation: str = ""
    limitations: list[str] = Field(default_factory=list)


class IntegratedView(Model):
    agreements: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class DataQuality(Model):
    missing_information: list[str] = Field(default_factory=list)
    stale_data: bool = False
    abstentions: list[str] = Field(default_factory=list)


class FinalAnalysis(Model):
    status: Literal["ANSWER", "CLARIFY", "ABSTAIN", "ERROR"]
    ticker: Ticker | None = None
    company_name: str | None = None
    analysis_type: Literal["technical", "fundamental", "full"]
    as_of: date | None = None
    executive_summary: str
    technical: Dimension = Field(default_factory=Dimension)
    fundamental: Dimension = Field(default_factory=Dimension)
    integrated_view: IntegratedView = Field(default_factory=IntegratedView)
    data_quality: DataQuality = Field(default_factory=DataQuality)
    sources: list[str] = Field(default_factory=list)
    trace_id: str
    session_id: str
    errors: list[ErrorInfo] = Field(default_factory=list)


class AgentState(Model):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    user_request: str
    resolved_asset: AssetResolution | None = None
    intent: UserIntent = Field(default_factory=UserIntent)
    observations: list[ToolResult] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    technical_data: MarketHistory | None = None
    technical_metrics: TechnicalMetrics | None = None
    financial_data: list[FinancialDocument] = Field(default_factory=list)
    methodology_evidence: list[Evidence] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    errors: list[ErrorInfo] = Field(default_factory=list)
    trace_events: list[dict[str, Any]] = Field(default_factory=list, exclude=True)
    iteration_count: int = 0
    status: Literal["RUNNING", "ANSWER", "CLARIFY", "ABSTAIN", "ERROR"] = "RUNNING"


class PendingAction(Model):
    action_id: str = Field(default_factory=lambda: str(uuid4()))
    action: Literal["add_to_watchlist", "create_monitoring_alert"]
    ticker: Ticker
    parameters: dict[str, Any] = Field(default_factory=dict)
    status: Literal["PAUSED", "APPROVE", "MODIFY", "REJECT"] = "PAUSED"
