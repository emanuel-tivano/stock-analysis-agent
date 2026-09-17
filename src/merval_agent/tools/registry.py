from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Literal

from pydantic import Field, ValidationError

from merval_agent.domain.errors import DecisionValidationError, ExternalServiceError
from merval_agent.domain.models import (
    AgentState,
    ErrorInfo,
    HistoryRange,
    Model,
    Ticker,
    ToolCall,
    ToolResult,
)
from merval_agent.domain.technical import calculate
from merval_agent.retrieval.local import MethodologyRetriever

from .assets import resolve_asset
from .operations import MAX_TOOL_ATTEMPTS, check_operation, operation_key, tool_error_type


class ResolveArgs(Model):
    query: str = Field(min_length=1, max_length=2000)


class AssetArgs(Model):
    ticker: Ticker


class HistoryArgs(AssetArgs):
    range: HistoryRange


class SearchArgs(Model):
    query: str = Field(min_length=1, max_length=2000)
    source: Literal["murphy", "graham"]


@dataclass
class Tool:
    name: str
    description: str
    args: type[Model]
    handler: Callable


class ToolRegistry:
    def __init__(self, tools: list[Tool]):
        self.tools = {t.name: t for t in tools}
        if len(self.tools) != len(tools):
            raise ValueError("Duplicate tool names")

    def schemas(self) -> list[dict]:
        return [
            {"name": t.name, "description": t.description, "parameters": t.args.model_json_schema()}
            for t in self.tools.values()
        ]

    def validate(self, call: ToolCall, state: AgentState) -> Model:
        if call.name not in self.tools:
            raise DecisionValidationError("UNKNOWN_TOOL")
        args = self.tools[call.name].args.model_validate(call.arguments)
        ticker = getattr(args, "ticker", None)
        if ticker and (not state.resolved_asset or state.resolved_asset.ticker != ticker):
            raise DecisionValidationError("UNRESOLVED_ASSET")
        if state.intent.analysis_type == "technical" and call.name in (
            "list_financial_documents",
            "get_latest_financial_statement",
        ):
            raise DecisionValidationError("TOOL_OUTSIDE_INTENT")
        if state.intent.analysis_type == "fundamental" and call.name in (
            "get_market_history",
            "calculate_technical_indicators",
        ):
            raise DecisionValidationError("TOOL_OUTSIDE_INTENT")
        if isinstance(args, SearchArgs):
            if (state.intent.analysis_type, args.source) in (
                ("technical", "graham"),
                ("fundamental", "murphy"),
            ):
                raise DecisionValidationError("METHODOLOGY_OUTSIDE_INTENT")
        if call.name == "calculate_technical_indicators" and state.technical_data is None:
            raise DecisionValidationError("HISTORY_REQUIRED")
        return args

    def prepare(self, call: ToolCall, state: AgentState):
        args = self.validate(call, state)
        key = operation_key(call, args.model_dump(), state)
        return args, key, check_operation(key, state)

    def execute(self, call: ToolCall, state: AgentState) -> ToolResult:
        started = perf_counter()
        key, attempt = None, 0
        try:
            args, key, attempt = self.prepare(call, state)
            data = self.tools[call.name].handler(args, state)
            return ToolResult(
                tool_name=call.name,
                success=True,
                data=data,
                operation_key=key,
                attempts=attempt,
                max_attempts=MAX_TOOL_ATTEMPTS,
                latency_ms=(perf_counter() - started) * 1000,
            )
        except (ValueError, ValidationError, ArithmeticError, ExternalServiceError) as exc:
            external = isinstance(exc, ExternalServiceError)
            calculation = (
                key is not None and call.name == "calculate_technical_indicators" and not external
            )
            kind, retryable = tool_error_type(exc) if external else ("INVALID_TOOL_CALL", False)
            if calculation:
                kind = "CALCULATION_ERROR"
            return ToolResult(
                tool_name=call.name,
                success=False,
                error=ErrorInfo(
                    code="EXTERNAL_SERVICE"
                    if external
                    else "CALCULATION_FAILED"
                    if calculation
                    else "INVALID_TOOL_CALL",
                    message="External service failed"
                    if external
                    else "Technical calculation failed"
                    if calculation
                    else "Tool arguments or preconditions invalid",
                    retryable=retryable,
                ),
                operation_key=key,
                attempts=attempt,
                max_attempts=MAX_TOOL_ATTEMPTS,
                error_kind=kind,
                can_retry=retryable and attempt < MAX_TOOL_ATTEMPTS,
                retry_budget_exhausted=retryable and attempt >= MAX_TOOL_ATTEMPTS,
                latency_ms=(perf_counter() - started) * 1000,
            )


def build_registry(market, bolsar, retriever: MethodologyRetriever) -> ToolRegistry:
    def latest(args, state):
        document = bolsar.find_latest_financial_statement(args.ticker)
        return {
            "document": document.model_dump(mode="json") if document else None,
            "availability": "AVAILABLE" if document else "INSUFFICIENT_DATA",
            "metrics_available": False,
        }

    return ToolRegistry(
        [
            Tool(
                "resolve_asset",
                "Resolve a ticker/company in BYMA. Use before data tools; clarify ambiguous instruments.",
                ResolveArgs,
                lambda a, s: resolve_asset(a.query).model_dump(mode="json"),
            ),
            Tool(
                "get_market_history",
                "Fetch OHLCV for technical analysis. Not for fundamental-only requests.",
                HistoryArgs,
                lambda a, s: market.get_history(a.ticker, a.range).model_dump(mode="json"),
            ),
            Tool(
                "calculate_technical_indicators",
                "Calculate deterministically from stored history; never supply LLM prices. Not for fundamentals.",
                AssetArgs,
                lambda a, s: calculate(s.technical_data.bars).model_dump(mode="json"),
            ),
            Tool(
                "list_financial_documents",
                "List Bolsar metadata for fundamentals; does not extract financial metrics. Not for technical-only requests.",
                AssetArgs,
                lambda a, s: {
                    "documents": [
                        d.model_dump(mode="json") for d in bolsar.list_documents(a.ticker)
                    ]
                },
            ),
            Tool(
                "get_latest_financial_statement",
                "Find latest statement metadata. No ratios or PDF extraction. Not for technical-only requests.",
                AssetArgs,
                latest,
            ),
            Tool(
                "search_methodology",
                "Retrieve Murphy/technical or Graham/fundamental methodology. Local DEMO notes are not book evidence.",
                SearchArgs,
                lambda a, s: {
                    "evidence": [
                        e.model_dump(mode="json") for e in retriever.search(a.query, a.source)
                    ]
                },
            ),
        ]
    )
