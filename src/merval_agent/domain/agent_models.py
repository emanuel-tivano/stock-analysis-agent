from datetime import date
from typing import Any, Literal
from uuid import uuid4

from pydantic import AwareDatetime, Field, model_validator

from .market_models import AssetResolution, ErrorInfo, MarketHistory, QuoteSnapshot
from .model_base import Model, Ticker
from .technical_models import TechnicalAssessment, TechnicalMetrics


class UserIntent(Model):
    analysis_type: Literal["technical", "fundamental", "full"] = "technical"


class RequestIntentAssessment(Model):
    """Internal deterministic classification of the original user request."""

    status: Literal["CLEAR", "MIXED", "CONTRADICTORY"] = "CLEAR"
    analysis_type: Literal["technical", "fundamental", "full"] | None = None
    conflict_code: (
        Literal[
            "TECHNICAL_REQUIRES_FUNDAMENTAL_EVIDENCE",
            "FUNDAMENTAL_REQUIRES_TECHNICAL_EVIDENCE",
        ]
        | None
    ) = None


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
    operation_key: str | None = None
    attempts: int = 0
    max_attempts: int = 2
    error_kind: str | None = None
    can_retry: bool = False
    retry_budget_exhausted: bool = False


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
        "SOURCE_ERROR",
        "STALE",
        "INVALID_DATA",
        "UNVERIFIED",
        "ASSET_NOT_FOUND",
        "AMBIGUOUS_ASSET",
        "UNSUPPORTED_ASSET",
    ] = "INSUFFICIENT_DATA"
    metrics: TechnicalMetrics | None = None
    history_only_metrics: TechnicalMetrics | None = None
    assessment: TechnicalAssessment | None = None
    narrative_origin: Literal["deterministic"] | None = None
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


class Generation(Model):
    mode: Literal["SIMULATED", "LLM_ORCHESTRATED", "DETERMINISTIC_FALLBACK", "FAILED"] = (
        "SIMULATED"
    )
    llm_status: Literal[
        "NOT_USED",
        "SUCCEEDED",
        "RATE_LIMITED",
        "QUOTA_EXHAUSTED",
        "UNAVAILABLE",
        "INVALID_OUTPUT",
        "CONFIGURATION_ERROR",
        "FAILED",
    ] = "NOT_USED"
    provider: str | None = None
    requested_model: str | None = None
    model: str | None = None
    model_version: str | None = None
    attempts: int = 0
    retry_after_seconds: float | None = Field(default=None, ge=0)
    warnings: list[str] = Field(default_factory=list)


class EditorialOptions(Model):
    focus: Literal["overview", "trend", "momentum", "risk"] = "overview"
    include_sections: list[Literal["overview", "trend", "momentum", "risk"]] = Field(
        default_factory=lambda: ["overview", "trend", "momentum", "risk"],
        min_length=1,
        max_length=4,
    )
    review_note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def valid_sections(self):
        if len(set(self.include_sections)) != len(self.include_sections):
            raise ValueError("Sections must be unique")
        if self.focus not in self.include_sections:
            raise ValueError("Focus must be included")
        if any(ord(c) < 32 and c not in "\n\t" for c in self.review_note):
            raise ValueError("Control characters are not allowed")
        return self


class PendingActionResponse(Model):
    action_id: str
    action_type: Literal["FINALIZE_TECHNICAL_REPORT"] = "FINALIZE_TECHNICAL_REPORT"
    status: Literal["PENDING", "MODIFIED", "APPROVED", "REJECTED", "EXECUTED"]
    version: int = Field(ge=1)
    summary: str
    ticker: Ticker
    as_of: date
    proposed_payload: EditorialOptions
    editable_fields: list[str] = Field(
        default_factory=lambda: ["focus", "include_sections", "review_note"]
    )
    available_actions: list[Literal["approve", "modify", "reject"]]
    trace_id: str
    session_id: str


class ReportPublication(Model):
    action_id: str
    approved_version: int = Field(ge=1)
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    editorial: EditorialOptions
    sections: dict[str, str]


class FinalAnalysis(Model):
    status: Literal["ANSWER", "CLARIFY", "ABSTAIN", "ERROR", "PAUSED"]
    pending_action: PendingActionResponse | None = None
    publication: ReportPublication | None = None
    ticker: Ticker | None = None
    company_name: str | None = None
    analysis_type: Literal["technical", "fundamental", "full"]
    as_of: date | None = None
    executive_summary: str
    generation: Generation = Field(default_factory=Generation)
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
    asset_validation_quote: QuoteSnapshot | None = Field(default=None, exclude=True)
    asset_validation_quote_attempted: bool = Field(default=False, exclude=True)
    intent: UserIntent = Field(default_factory=UserIntent)
    request_intent_assessment: RequestIntentAssessment = Field(
        default_factory=RequestIntentAssessment, exclude=True
    )
    observations: list[ToolResult] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    technical_data: MarketHistory | None = None
    technical_metrics: TechnicalMetrics | None = None
    technical_assessment: TechnicalAssessment | None = None
    technical_evaluated_at: AwareDatetime | None = Field(default=None, exclude=True)
    missing_information: list[str] = Field(default_factory=list)
    errors: list[ErrorInfo] = Field(default_factory=list)
    trace_events: list[dict[str, Any]] = Field(default_factory=list, exclude=True)
    iteration_count: int = 0
    status: Literal["RUNNING", "ANSWER", "CLARIFY", "ABSTAIN", "ERROR", "PAUSED"] = "RUNNING"
