import hashlib
import json
import logging
import re
from collections.abc import Callable
from datetime import datetime
from typing import get_args

from merval_agent.adapters.llm.base import LLMProvider
from merval_agent.domain.actions import EvidenceSnapshot, PendingAction, digest, requests_review
from merval_agent.domain.errors import DecisionBudgetExhausted, ExternalServiceError
from merval_agent.domain.models import (
    AgentDecision,
    AgentState,
    ErrorInfo,
    HistoryRange,
    ToolCall,
    ToolResult,
    now,
)
from merval_agent.domain.technical_assessment import assess, is_answerable
from merval_agent.memory.repository import AnalysisRepository
from merval_agent.tools.registry import ToolRegistry

from .decisions import resolve_effective_terminal_action, validate_decision
from .generation import describe_generation
from .intent import explicit_analysis_type
from .report import build_report
from .state import reduce_observation
from .validation_feedback import validation_feedback

logger = logging.getLogger("merval_agent")


def event(name: str, state: AgentState, **fields):
    record = {
        "event": name,
        "trace_id": state.trace_id,
        "step": state.iteration_count,
        "status": state.status,
        "outcome": fields.pop("outcome", state.status),
        "state": {
            "ticker": state.resolved_asset.ticker if state.resolved_asset else None,
            "analysis_type": state.intent.analysis_type,
            "methodology_requested_by_model": state.intent.methodology,
            "observations": len(state.observations),
            "has_history": state.technical_data is not None,
            "has_metrics": state.technical_metrics is not None,
            "documents": len(state.financial_data),
            "methodology_kinds": sorted({e.kind for e in state.methodology_evidence}),
        },
        **fields,
    }
    state.trace_events.append(record)
    logger.info(json.dumps(record))


class EquityAgent:
    def __init__(
        self,
        provider: LLMProvider,
        tools: ToolRegistry,
        repository: AnalysisRepository,
        max_steps: int = 12,
        stale_after_days: int = 7,
        deterministic_fallback: bool = True,
        clock: Callable[[], datetime] | None = None,
    ):
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        self.provider, self.tools, self.repository = provider, tools, repository
        self.max_steps, self.stale_after_days = max_steps, stale_after_days
        self.deterministic_fallback = deterministic_fallback
        self.clock = clock or now

    def run(self, message: str, session_id: str | None = None):
        state = AgentState(
            user_request=message, **({"session_id": session_id} if session_id else {})
        )
        analysis_type = explicit_analysis_type(message)
        if analysis_type is not None:
            state.intent.analysis_type = analysis_type
        event("AGENT_STARTED", state)
        summary, interpretation = "Se alcanzó MAX_AGENT_STEPS sin evidencia suficiente.", ""
        consecutive_invalid = 0
        degraded = False
        technical_snapshot_sha256 = None

        def refresh_technical_snapshot():
            nonlocal technical_snapshot_sha256
            if not state.resolved_asset or state.resolved_asset.status != "RESOLVED":
                state.technical_assessment = None
                state.technical_evaluated_at = None
                technical_snapshot_sha256 = None
                return
            snapshot_sha256 = digest(
                {
                    "history": state.technical_data.model_dump(mode="json")
                    if state.technical_data
                    else None,
                    "metrics": state.technical_metrics.model_dump(mode="json")
                    if state.technical_metrics
                    else None,
                }
            )
            if (
                snapshot_sha256 == technical_snapshot_sha256
                and state.technical_assessment is not None
                and state.technical_evaluated_at is not None
            ):
                return
            evaluated_at = self.clock()
            if evaluated_at.tzinfo is None:
                raise ValueError("Agent clock must return a timezone-aware datetime")
            state.technical_evaluated_at = evaluated_at
            state.technical_assessment = assess(
                state.technical_data,
                state.technical_metrics,
                evaluated_at,
                self.stale_after_days,
            )
            if state.technical_data:
                history = state.technical_data
                quote = history.quote
                event(
                    "TECHNICAL_ASSESSED",
                    state,
                    assessment_status=state.technical_assessment.status,
                    provider_fetched_at=history.provider_fetched_at.isoformat(),
                    received_at=history.received_at.isoformat(),
                    evaluated_at=evaluated_at.isoformat(),
                    provider_clock_skew_ms=(
                        history.provider_fetched_at - history.received_at
                    ).total_seconds()
                    * 1000,
                    quote_observed_at=quote.observed_at.isoformat() if quote else None,
                    quote_provider_fetched_at=(
                        quote.provider_fetched_at.isoformat()
                        if quote and quote.provider_fetched_at
                        else None
                    ),
                    quote_received_at=quote.received_at.isoformat() if quote else None,
                    quote_provider_clock_skew_ms=(
                        (quote.provider_fetched_at - quote.received_at).total_seconds() * 1000
                        if quote and quote.provider_fetched_at
                        else None
                    ),
                )
            technical_snapshot_sha256 = snapshot_sha256

        while state.status == "RUNNING" and state.iteration_count < self.max_steps:
            state.iteration_count += 1
            refresh_technical_snapshot()
            try:
                validated_provider = getattr(self.provider, "decide_validated", None)
                if validated_provider:

                    def validate_proposal(proposal):
                        validate_decision(proposal, state)
                        candidate = state.model_copy(deep=True)
                        if proposal.intent:
                            candidate.intent = proposal.intent
                        if proposal.action == "CALL_TOOL":
                            call = ToolCall(name=proposal.tool_name, arguments=proposal.tool_args)
                            self.tools.prepare(call, candidate)

                    raw = validated_provider(
                        state.model_copy(deep=True),
                        self.tools.schemas(),
                        validate_proposal,
                        lambda name, **fields: event(name, state, **fields),
                        self.max_steps,
                    )
                else:
                    raw = self.provider.decide(state.model_copy(deep=True), self.tools.schemas())
                decision = AgentDecision.model_validate(raw)
                validate_decision(decision, state)
                candidate = state.model_copy(deep=True)
                if decision.intent:
                    candidate.intent = decision.intent
                if decision.action == "CALL_TOOL":
                    normalized, op_key, attempt = self.tools.prepare(
                        ToolCall(name=decision.tool_name, arguments=decision.tool_args), candidate
                    )
                consecutive_invalid = 0
                if decision.intent:
                    state.intent = decision.intent
                effective_action = decision.action
                terminal_resolution = None
                if decision.action != "CALL_TOOL":
                    terminal_resolution = resolve_effective_terminal_action(decision.action, state)
                    effective_action = terminal_resolution.effective_action
                overridden = bool(terminal_resolution and terminal_resolution.override_reason)
                if validated_provider:
                    if decision.missing_information and not overridden:
                        state.missing_information.append(
                            "El modelo indicó información faltante; revisar evidencia disponible."
                        )
                elif not overridden:
                    state.missing_information.extend(decision.missing_information)
                event(
                    "DECISION_MADE",
                    state,
                    action=decision.action,
                    tool_name=decision.tool_name
                    if decision.tool_name in self.tools.tools
                    else None,
                    confidence=decision.confidence,
                    missing_count=len(decision.missing_information),
                    evaluated_at=state.technical_evaluated_at.isoformat()
                    if state.technical_evaluated_at
                    else None,
                )
                if overridden:
                    event(
                        "TERMINAL_ACTION_OVERRIDDEN",
                        state,
                        proposed_action=terminal_resolution.proposed_action,
                        effective_action=terminal_resolution.effective_action,
                        override_reason=terminal_resolution.override_reason,
                        assessment_status=state.technical_assessment.status
                        if state.technical_assessment
                        else None,
                    )
                if decision.action == "CALL_TOOL":
                    call = ToolCall(
                        name=decision.tool_name,
                        arguments=normalized.model_dump(exclude_none=True),
                        step_number=state.iteration_count,
                    )
                    state.tool_calls.append(call)
                    safe_args = {
                        k: v
                        for k, v in call.arguments.items()
                        if isinstance(v, str)
                        and (
                            (k == "range" and v in get_args(HistoryRange))
                            or (k == "source" and v in ("murphy", "graham"))
                            or (
                                k == "ticker"
                                and state.resolved_asset
                                and v == state.resolved_asset.ticker
                            )
                            or (call.name == "resolve_asset" and k == "symbol")
                            or (
                                call.name == "resolve_asset"
                                and k == "market"
                                and v.casefold() in ("bcba", "byma")
                            )
                        )
                    }
                    event(
                        "TOOL_STARTED",
                        state,
                        tool_name=call.name if call.name in self.tools.tools else "unknown",
                        arguments=safe_args,
                        arguments_sha256=hashlib.sha256(
                            json.dumps(call.arguments, sort_keys=True).encode()
                        ).hexdigest(),
                        operation_key=op_key,
                    )
                    result = self.tools.execute(call, state)
                    try:
                        reduce_observation(state, result)
                    except (ValueError, KeyError, TypeError):
                        # A malformed tool result is a tool failure, not an invalid LLM decision.
                        result = ToolResult(
                            tool_name=call.name,
                            success=False,
                            error=ErrorInfo(
                                code="EXTERNAL_SERVICE", message="Invalid tool response"
                            ),
                            error_kind="INVALID_RESPONSE",
                            operation_key=op_key,
                            attempts=attempt,
                            latency_ms=result.latency_ms,
                        )
                        reduce_observation(state, result)
                    event(
                        "TOOL_SUCCEEDED" if result.success else "TOOL_FAILED",
                        state,
                        tool_name=call.name if call.name in self.tools.tools else "unknown",
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
                        **(
                            {
                                "market_data": {
                                    "as_of": str(state.technical_data.bars[-1].date),
                                    "history_as_of": str(
                                        state.technical_data.bars[
                                            -2
                                            if state.technical_data.enrichment_status == "appended"
                                            else -1
                                        ].date
                                    ),
                                    "history_source": state.technical_data.source,
                                    "quote_source": state.technical_data.quote.source
                                    if state.technical_data.quote
                                    else None,
                                    "quote_in_indicators": state.technical_data.enrichment_status
                                    == "appended",
                                    "fetched_at": state.technical_data.fetched_at.isoformat(),
                                    "provider_fetched_at": state.technical_data.provider_fetched_at.isoformat(),
                                    "received_at": state.technical_data.received_at.isoformat(),
                                    "provider_clock_skew_ms": (
                                        state.technical_data.provider_fetched_at
                                        - state.technical_data.received_at
                                    ).total_seconds()
                                    * 1000,
                                    "enrichment_status": state.technical_data.enrichment_status,
                                    "discarded_rows": state.technical_data.discarded_rows,
                                    "provisional": state.technical_data.quote is not None,
                                    "quote_observed_at": state.technical_data.quote.observed_at.isoformat()
                                    if state.technical_data.quote
                                    else None,
                                    "quote_fetched_at": state.technical_data.quote.fetched_at.isoformat()
                                    if state.technical_data.quote
                                    else None,
                                    "quote_provider_fetched_at": (
                                        state.technical_data.quote.provider_fetched_at.isoformat()
                                        if state.technical_data.quote
                                        and state.technical_data.quote.provider_fetched_at
                                        else None
                                    ),
                                    "quote_received_at": (
                                        state.technical_data.quote.received_at.isoformat()
                                        if state.technical_data.quote
                                        else None
                                    ),
                                    "quote_provider_clock_skew_ms": (
                                        (
                                            state.technical_data.quote.provider_fetched_at
                                            - state.technical_data.quote.received_at
                                        ).total_seconds()
                                        * 1000
                                        if state.technical_data.quote
                                        and state.technical_data.quote.provider_fetched_at
                                        else None
                                    ),
                                    "snapshot_sha256": hashlib.sha256(
                                        state.technical_data.model_dump_json().encode()
                                    ).hexdigest(),
                                }
                            }
                            if result.success
                            and call.name == "get_market_history"
                            and state.technical_data
                            and state.technical_data.bars
                            else {}
                        ),
                    )
                    if (
                        result.success
                        and call.name == "resolve_asset"
                        and state.resolved_asset
                        and state.resolved_asset.status == "RESOLVED"
                    ):
                        resolution = state.resolved_asset
                        event(
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
                    if (
                        result.success
                        and call.name == "resolve_asset"
                        and state.resolved_asset
                        and state.resolved_asset.status != "RESOLVED"
                    ):
                        resolution = state.resolved_asset
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
                                state.missing_information.append(
                                    "Ticker existente o nombre de empresa identificable"
                                )
                            else:
                                summary = (
                                    "No pude identificar un activo inequívoco. Indicá el ticker "
                                    "o el nombre completo de la empresa."
                                )
                                state.missing_information.append(
                                    "Ticker o nombre de empresa identificable"
                                )
                        else:
                            state.status = "CLARIFY"
                            summary = (
                                "El activo es ambiguo. Indicá el ticker exacto o especificá el "
                                "instrumento y mercado que querés analizar."
                            )
                            state.missing_information.append("Ticker e instrumento inequívocos")
                        interpretation = ""
                        event(
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
                else:
                    state.status = {
                        "FINAL_ANSWER": "ANSWER",
                        "CLARIFY": "CLARIFY",
                        "ABSTAIN": "ABSTAIN",
                    }[effective_action]
                    summary, interpretation = decision.reason, decision.interpretation
                    resolution_provider_failure = next(
                        (
                            observation
                            for observation in reversed(state.observations)
                            if observation.tool_name == "resolve_asset"
                        ),
                        None,
                    )
                    if (
                        resolution_provider_failure
                        and not resolution_provider_failure.success
                        and resolution_provider_failure.error
                        and resolution_provider_failure.error.code == "EXTERNAL_SERVICE"
                    ):
                        state.status = "ERROR"
                        summary = (
                            "No se pudo verificar el instrumento por una falla del proveedor; "
                            "no se lo clasificó como inexistente."
                        )
                        interpretation = ""
                    if validated_provider:
                        # The report renders financial prose from Python assessment.
                        # Model operational text is not verified financial evidence.
                        summary = {
                            "FINAL_ANSWER": "Evaluación técnica completada.",
                            "ABSTAIN": "No hay evidencia suficiente para completar el análisis solicitado.",
                            "CLARIFY": "Confirmá el ticker, instrumento BYMA y tipo de análisis; aclarar pedidos ambiguos o contradictorios.",
                        }[effective_action]
                        interpretation = ""
                event("STATE_UPDATED", state, transition=f"RUNNING->{state.status}")
            except ValueError as exc:
                consecutive_invalid += 1
                feedback = validation_feedback(exc, "agent_validation")
                error = ErrorInfo(
                    code="INVALID_DECISION", message="Decision failed schema or business validation"
                )
                state.errors.append(error)
                state.observations.append(
                    ToolResult(tool_name="decision", success=False, error=error, data=feedback)
                )
                event(
                    "DECISION_MADE",
                    state,
                    outcome="INVALID",
                    error=error.code,
                    validation_feedback=feedback,
                    evaluated_at=state.technical_evaluated_at.isoformat()
                    if state.technical_evaluated_at
                    else None,
                )
                if consecutive_invalid >= 2 or state.iteration_count == self.max_steps:
                    state.status = "ERROR"
                    summary = "No fue posible obtener una decisión válida dentro del presupuesto."
                event(
                    "STATE_UPDATED", state, error=error.code, transition=f"RUNNING->{state.status}"
                )
            except ExternalServiceError as exc:
                state.status = "ERROR"
                failure_code = (
                    "DECISION_BUDGET_EXHAUSTED"
                    if isinstance(exc, DecisionBudgetExhausted)
                    else "LLM_FAILURE"
                )
                state.errors.append(
                    ErrorInfo(
                        code=failure_code,
                        message="Provider unavailable or malformed output",
                        retryable=failure_code == "LLM_FAILURE" and exc.retryable,
                    )
                )
                summary = "No fue posible obtener una decisión válida del provider."
                if (
                    self.deterministic_fallback
                    and not isinstance(exc, DecisionBudgetExhausted)
                    and exc.classification in ("RATE_LIMITED", "QUOTA_EXHAUSTED", "UNAVAILABLE")
                    and state.intent.analysis_type == "technical"
                    and not re.search(r"\b(murphy|graham)\b", state.user_request, re.I)
                    and state.resolved_asset
                    and state.resolved_asset.ticker
                    and is_answerable(state.technical_assessment)
                ):
                    state.status = "ANSWER"
                    degraded = True
                event(
                    "STATE_UPDATED",
                    state,
                    error=failure_code,
                    transition=f"RUNNING->{state.status}",
                )
            except Exception:
                state.status = "ERROR"
                state.errors.append(
                    ErrorInfo(code="INTERNAL_ERROR", message="Unexpected execution failure")
                )
                summary = "La ejecución terminó con un error técnico registrado."
                event("STATE_UPDATED", state, error="INTERNAL_ERROR", transition="RUNNING->ERROR")
        refresh_technical_snapshot()
        previous_status = state.status
        if state.status == "RUNNING":
            state.status = "ERROR"
            state.errors.append(
                ErrorInfo(code="MAX_STEPS_EXCEEDED", message="Decision budget exhausted")
            )
            state.missing_information.append("Límite de pasos alcanzado")
        result = build_report(
            state,
            summary,
            interpretation,
            self.stale_after_days,
            reference_time=state.technical_evaluated_at,
        )
        result.generation = describe_generation(state.trace_events, result.status, degraded)
        if result.generation.mode == "DETERMINISTIC_FALLBACK":
            result.technical.limitations.extend(result.generation.warnings)
        if previous_status != "ERROR" or state.status != "ERROR":
            event("STATE_UPDATED", state, transition=f"{previous_status}->{state.status}")
        if result.status == "ABSTAIN":
            event("AGENT_ABSTAINED", state)
        pending_action = None
        if (
            requests_review(message)
            and result.status == "ANSWER"
            and result.analysis_type == "technical"
            and is_answerable(result.technical.assessment)
            and state.technical_data
        ):
            snapshot = EvidenceSnapshot(
                report=result.model_copy(deep=True),
                history=state.technical_data,
                evaluated_at=state.technical_evaluated_at,
            )
            pending_action = PendingAction(
                trace_id=state.trace_id,
                session_id=state.session_id,
                evidence_snapshot=snapshot,
                snapshot_sha256=digest(snapshot),
            )
            state.status = result.status = "PAUSED"
            result.pending_action = pending_action.public()
            result.executive_summary = (
                "Borrador preparado para revisión; todavía no se finalizó el informe."
            )
        event(
            "AGENT_FINISHED",
            state,
            generation=result.generation.model_dump(mode="json"),
            evaluated_at=state.technical_evaluated_at.isoformat()
            if state.technical_evaluated_at
            else None,
            final_reason=(
                state.errors[-1].code
                if state.status == "ERROR" and state.errors
                else {
                    "ANSWER": "AVAILABLE_DATA_WITH_LIMITATIONS",
                    "CLARIFY": "USER_INFORMATION_REQUIRED",
                    "ABSTAIN": "INSUFFICIENT_EVIDENCE",
                }.get(state.status, state.status)
            ),
        )
        try:
            if pending_action is not None:
                self.repository.save(state, result, pending_action=pending_action)
            else:
                self.repository.save(state, result)
        except Exception:
            previous_status = state.status
            state.status = "ERROR"
            result.status = "ERROR"
            result.pending_action = None
            result.errors.append(
                ErrorInfo(code="PERSISTENCE_FAILURE", message="Could not persist execution")
            )
            event(
                "STATE_UPDATED",
                state,
                error="PERSISTENCE_FAILURE",
                **(
                    {"transition": f"{previous_status}->ERROR"}
                    if previous_status != "ERROR"
                    else {}
                ),
            )
            event("AGENT_FINISHED", state, error="PERSISTENCE_FAILURE")
        return result
