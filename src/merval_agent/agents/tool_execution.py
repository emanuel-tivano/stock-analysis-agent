import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, get_args

from merval_agent.domain.models import (
    AgentDecision,
    AgentState,
    ErrorInfo,
    HistoryRange,
    ToolCall,
    ToolResult,
)
from merval_agent.tools.registry import ToolRegistry

from .state import reduce_observation


@dataclass(frozen=True)
class ToolExecutionOutcome:
    summary: str | None = None
    interpretation: str = ""


def execute_tool_decision(
    state: AgentState,
    decision: AgentDecision,
    tools: ToolRegistry,
    normalized: Any,
    operation_key: str,
    attempt: int,
    *,
    emit: Callable[..., None],
) -> ToolExecutionOutcome:
    call = ToolCall(
        name=decision.tool_name,
        arguments=normalized.model_dump(exclude_none=True),
        step_number=state.iteration_count,
    )
    state.tool_calls.append(call)
    safe_args = {
        key: value
        for key, value in call.arguments.items()
        if isinstance(value, str)
        and (
            (key == "range" and value in get_args(HistoryRange))
            or (
                key == "ticker"
                and state.resolved_asset
                and value == state.resolved_asset.ticker
            )
            or (call.name == "resolve_asset" and key == "symbol")
            or (
                call.name == "resolve_asset"
                and key == "market"
                and value.casefold() in ("bcba", "byma")
            )
        )
    }
    emit(
        "TOOL_STARTED",
        state,
        tool_name=call.name if call.name in tools.tools else "unknown",
        arguments=safe_args,
        arguments_sha256=hashlib.sha256(
            json.dumps(call.arguments, sort_keys=True).encode()
        ).hexdigest(),
        operation_key=operation_key,
    )
    result = tools.execute(call, state)
    try:
        reduce_observation(state, result)
    except (ValueError, KeyError, TypeError):
        result = ToolResult(
            tool_name=call.name,
            success=False,
            error=ErrorInfo(code="EXTERNAL_SERVICE", message="Invalid tool response"),
            error_kind="INVALID_RESPONSE",
            operation_key=operation_key,
            attempts=attempt,
            latency_ms=result.latency_ms,
        )
        reduce_observation(state, result)
    emit(
        "TOOL_SUCCEEDED" if result.success else "TOOL_FAILED",
        state,
        tool_name=call.name if call.name in tools.tools else "unknown",
        outcome="SUCCEEDED" if result.success else "FAILED",
        latency_ms=result.latency_ms,
        error=result.error.code if result.error else None,
        operation_key=result.operation_key,
        attempts=result.attempts,
        max_attempts=result.max_attempts,
        error_kind=result.error_kind,
        retryable=result.error.retryable if result.error else False,
        can_retry=result.can_retry,
        retry_budget_exhausted=result.retry_budget_exhausted,
        **_market_data_event(state, call, result),
    )
    if result.success and call.name == "resolve_asset" and state.resolved_asset:
        return _resolved_asset_outcome(state, call, emit)
    return ToolExecutionOutcome()


def _market_data_event(state: AgentState, call: ToolCall, result: ToolResult) -> dict:
    if not (
        result.success
        and call.name == "get_market_history"
        and state.technical_data
        and state.technical_data.bars
    ):
        return {}
    history = state.technical_data
    quote = history.quote
    market_data = {
        "as_of": str(history.bars[-1].date),
        "history_as_of": str(
            history.bars[-2 if history.enrichment_status == "appended" else -1].date
        ),
        "history_source": history.source,
        "quote_source": quote.source if quote else None,
        "quote_in_indicators": history.enrichment_status == "appended",
        "fetched_at": history.fetched_at.isoformat(),
        "provider_fetched_at": history.provider_fetched_at.isoformat(),
        "received_at": history.received_at.isoformat(),
        "provider_clock_skew_ms": (
            history.provider_fetched_at - history.received_at
        ).total_seconds()
        * 1000,
        "enrichment_status": history.enrichment_status,
        "discarded_rows": history.discarded_rows,
        "provisional": quote is not None,
        "quote_observed_at": quote.observed_at.isoformat() if quote else None,
        "quote_fetched_at": quote.fetched_at.isoformat() if quote else None,
        "quote_provider_fetched_at": (
            quote.provider_fetched_at.isoformat() if quote and quote.provider_fetched_at else None
        ),
        "quote_received_at": quote.received_at.isoformat() if quote else None,
        "quote_provider_clock_skew_ms": (
            (quote.provider_fetched_at - quote.received_at).total_seconds() * 1000
            if quote and quote.provider_fetched_at
            else None
        ),
        "snapshot_sha256": hashlib.sha256(history.model_dump_json().encode()).hexdigest(),
    }
    if history.discarded_details:
        market_data["discarded_details"] = [
            detail.model_dump(mode="json", exclude_none=True)
            for detail in history.discarded_details
        ]
    return {"market_data": market_data}


def _resolved_asset_outcome(
    state: AgentState,
    call: ToolCall,
    emit: Callable[..., None],
) -> ToolExecutionOutcome:
    resolution = state.resolved_asset
    if resolution.status == "RESOLVED":
        emit(
            "ASSET_RESOLVED",
            state,
            proposed_symbol=call.arguments.get("symbol"),
            proposed_market=call.arguments.get("market"),
            ticker=resolution.ticker,
            market=resolution.market,
            validation_method=resolution.validation_method,
            validation_status=resolution.validation_status,
            validation_source=resolution.validation_source,
            existence_status=resolution.existence_status,
            eligibility_status=resolution.eligibility_status,
            eligibility_reason=resolution.eligibility_reason,
            eligibility_method=resolution.eligibility_method,
        )
        return ToolExecutionOutcome()

    if resolution.status == "UNSUPPORTED":
        state.status = "ABSTAIN"
        summary = (
            "El instrumento fue identificado, pero está fuera del universo "
            "de acciones domésticas argentinas soportado por este agente."
        )
    elif resolution.status == "NOT_FOUND":
        state.status = "CLARIFY"
        requested = resolution.requested_symbol
        if resolution.validation_status == "INVALID_FORMAT":
            summary = (
                f"El símbolo propuesto {requested} no tiene un formato válido. "
                "Verificá el ticker o ingresá el nombre de la empresa."
            )
            state.missing_information.append("Ticker con formato válido")
        elif resolution.validation_status == "NOT_FOUND":
            summary = (
                f"El proveedor de mercado no encontró evidencia de {requested}. "
                "Verificá el ticker o ingresá el nombre de la empresa."
            )
            state.missing_information.append("Ticker existente o nombre de empresa identificable")
        else:
            summary = (
                "No pude identificar un activo inequívoco. Indicá el ticker "
                "o el nombre completo de la empresa."
            )
            state.missing_information.append("Ticker o nombre de empresa identificable")
    else:
        state.status = "CLARIFY"
        summary = (
            "El activo es ambiguo. Indicá el ticker exacto o especificá el "
            "instrumento y mercado que querés analizar."
        )
        state.missing_information.append("Ticker e instrumento inequívocos")

    emit(
        "ASSET_RESOLUTION_FAILED",
        state,
        reason=resolution.status,
        requested_symbol=resolution.requested_symbol,
        alternatives_count=len(resolution.alternatives),
        proposed_symbol=call.arguments.get("symbol"),
        proposed_market=call.arguments.get("market"),
        validation_method=resolution.validation_method,
        validation_status=resolution.validation_status,
        validation_source=resolution.validation_source,
        existence_status=resolution.existence_status,
        eligibility_status=resolution.eligibility_status,
        eligibility_reason=resolution.eligibility_reason,
        eligibility_method=resolution.eligibility_method,
    )
    return ToolExecutionOutcome(summary)
