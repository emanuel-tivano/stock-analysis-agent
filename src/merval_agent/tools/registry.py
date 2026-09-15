from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Literal

from pydantic import Field, ValidationError

from merval_agent.domain.errors import ExternalServiceError
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
            raise ValueError("Unknown tool")
        args = self.tools[call.name].args.model_validate(call.arguments)
        ticker = getattr(args, "ticker", None)
        if ticker and (not state.resolved_asset or state.resolved_asset.ticker != ticker):
            raise ValueError("Resolve asset before requesting its data")
        if state.intent.analysis_type == "technical" and call.name in (
            "list_financial_documents",
            "get_latest_financial_statement",
        ):
            raise ValueError("Fundamental tool outside technical intent")
        if state.intent.analysis_type == "fundamental" and call.name in (
            "get_market_history",
            "calculate_technical_indicators",
        ):
            raise ValueError("Technical tool outside fundamental intent")
        if isinstance(args, SearchArgs):
            if (state.intent.analysis_type, args.source) in (
                ("technical", "graham"),
                ("fundamental", "murphy"),
            ):
                raise ValueError("Methodology outside intent")
        if call.name == "calculate_technical_indicators" and state.technical_data is None:
            raise ValueError("Fetch history first")
        return args

    def execute(self, call: ToolCall, state: AgentState) -> ToolResult:
        started = perf_counter()
        try:
            args = self.validate(call, state)
            data = self.tools[call.name].handler(args, state)
            return ToolResult(
                tool_name=call.name,
                success=True,
                data=data,
                latency_ms=(perf_counter() - started) * 1000,
            )
        except (ValueError, ValidationError, ExternalServiceError) as exc:
            external = isinstance(exc, ExternalServiceError)
            return ToolResult(
                tool_name=call.name,
                success=False,
                error=ErrorInfo(
                    code="EXTERNAL_SERVICE" if external else "INVALID_TOOL_CALL",
                    message="External service failed"
                    if external
                    else "Tool arguments or preconditions invalid",
                    retryable=external,
                ),
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
