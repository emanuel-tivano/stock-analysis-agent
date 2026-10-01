import re
from collections.abc import Callable
from datetime import datetime

from merval_agent.adapters.llm.base import LLMProvider
from merval_agent.domain.errors import DecisionBudgetExhausted, ExternalServiceError
from merval_agent.domain.models import (
    AgentDecision,
    AgentState,
    ErrorInfo,
    ToolCall,
    ToolResult,
    now,
)
from merval_agent.domain.technical_assessment import is_answerable
from merval_agent.memory.repository import AnalysisRepository
from merval_agent.tools.registry import ToolRegistry

from .decisions import resolve_effective_terminal_action, validate_decision
from .finalization import finalize_run
from .intent import assess_request_intent
from .technical_snapshot import refresh_technical_snapshot
from .tool_execution import execute_tool_decision
from .trace import event
from .validation_feedback import validation_feedback


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
        request_assessment = assess_request_intent(message)
        state = AgentState(
            user_request=message,
            request_intent_assessment=request_assessment,
            **({"session_id": session_id} if session_id else {}),
        )
        if request_assessment.analysis_type is not None:
            state.intent.analysis_type = request_assessment.analysis_type
        event("AGENT_STARTED", state)

        summary = "Se alcanzó MAX_AGENT_STEPS sin evidencia suficiente."
        interpretation = ""
        if request_assessment.status == "CONTRADICTORY":
            state.status = "CLARIFY"
            state.missing_information.append(
                "Aclaración del tipo de análisis y la evidencia que debe fundamentarlo"
            )
            summary = (
                "El tipo de análisis solicitado y la evidencia indicada son incompatibles. "
                "Aclaralo antes de continuar."
            )
            event(
                "REQUEST_CLARIFICATION_REQUIRED",
                state,
                reason=request_assessment.conflict_code,
                requested_analysis_type=request_assessment.analysis_type,
            )

        consecutive_invalid = 0
        degraded = False
        technical_snapshot_sha256 = None

        while state.status == "RUNNING" and state.iteration_count < self.max_steps:
            state.iteration_count += 1
            technical_snapshot_sha256 = refresh_technical_snapshot(
                state,
                technical_snapshot_sha256,
                clock=self.clock,
                stale_after_days=self.stale_after_days,
                emit=event,
            )
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
                    normalized, operation_key, attempt = self.tools.prepare(
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
                    tool_name=(
                        decision.tool_name if decision.tool_name in self.tools.tools else None
                    ),
                    confidence=decision.confidence,
                    missing_count=len(decision.missing_information),
                    evaluated_at=(
                        state.technical_evaluated_at.isoformat()
                        if state.technical_evaluated_at
                        else None
                    ),
                )
                if overridden:
                    event(
                        "TERMINAL_ACTION_OVERRIDDEN",
                        state,
                        proposed_action=terminal_resolution.proposed_action,
                        effective_action=terminal_resolution.effective_action,
                        override_reason=terminal_resolution.override_reason,
                        assessment_status=(
                            state.technical_assessment.status
                            if state.technical_assessment
                            else None
                        ),
                    )

                if decision.action == "CALL_TOOL":
                    outcome = execute_tool_decision(
                        state,
                        decision,
                        self.tools,
                        normalized,
                        operation_key,
                        attempt,
                        emit=event,
                    )
                    if outcome.summary is not None:
                        summary = outcome.summary
                        interpretation = outcome.interpretation
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
                        summary = {
                            "FINAL_ANSWER": "Evaluación técnica completada.",
                            "ABSTAIN": (
                                "No hay evidencia suficiente para completar el análisis solicitado."
                            ),
                            "CLARIFY": (
                                "Confirmá el ticker, instrumento BYMA y tipo de análisis; "
                                "aclarar pedidos ambiguos o contradictorios."
                            ),
                        }[effective_action]
                        interpretation = ""
                event("STATE_UPDATED", state, transition=f"RUNNING->{state.status}")
            except ValueError as exc:
                consecutive_invalid += 1
                feedback = validation_feedback(exc, "agent_validation")
                error = ErrorInfo(
                    code="INVALID_DECISION",
                    message="Decision failed schema or business validation",
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
                    evaluated_at=(
                        state.technical_evaluated_at.isoformat()
                        if state.technical_evaluated_at
                        else None
                    ),
                )
                if consecutive_invalid >= 2 or state.iteration_count == self.max_steps:
                    state.status = "ERROR"
                    summary = "No fue posible obtener una decisión válida dentro del presupuesto."
                event("STATE_UPDATED", state, error=error.code, transition=f"RUNNING->{state.status}")
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
                    and not re.search(r"\bmurphy\b", state.user_request, re.I)
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

        refresh_technical_snapshot(
            state,
            technical_snapshot_sha256,
            clock=self.clock,
            stale_after_days=self.stale_after_days,
            emit=event,
        )
        return finalize_run(
            state,
            message=message,
            summary=summary,
            interpretation=interpretation,
            stale_after_days=self.stale_after_days,
            degraded=degraded,
            repository=self.repository,
            emit=event,
        )
