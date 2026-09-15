import json
import logging
from typing import get_args

from merval_agent.adapters.llm.base import LLMProvider
from merval_agent.domain.errors import ExternalServiceError
from merval_agent.domain.models import (
    AgentDecision,
    AgentState,
    ErrorInfo,
    HistoryRange,
    ToolCall,
    ToolResult,
)
from merval_agent.memory.repository import AnalysisRepository
from merval_agent.tools.registry import ToolRegistry

from .decisions import validate_decision
from .report import build_report
from .state import reduce_observation

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
    ):
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        self.provider, self.tools, self.repository = provider, tools, repository
        self.max_steps, self.stale_after_days = max_steps, stale_after_days

    def run(self, message: str, session_id: str | None = None):
        state = AgentState(
            user_request=message, **({"session_id": session_id} if session_id else {})
        )
        event("AGENT_STARTED", state)
        summary, interpretation = "Se alcanzó MAX_AGENT_STEPS sin evidencia suficiente.", ""
        while state.status == "RUNNING" and state.iteration_count < self.max_steps:
            state.iteration_count += 1
            try:
                raw = self.provider.decide(state.model_copy(deep=True), self.tools.schemas())
                decision = AgentDecision.model_validate(raw)
                validate_decision(decision, state)
                if decision.intent:
                    state.intent = decision.intent
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
                )
                if decision.action == "CALL_TOOL":
                    call = ToolCall(
                        name=decision.tool_name,
                        arguments=decision.tool_args,
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
                        )
                    }
                    event(
                        "TOOL_STARTED",
                        state,
                        tool_name=call.name if call.name in self.tools.tools else "unknown",
                        arguments=safe_args,
                    )
                    result = self.tools.execute(call, state)
                    reduce_observation(state, result)
                    event(
                        "TOOL_SUCCEEDED" if result.success else "TOOL_FAILED",
                        state,
                        tool_name=call.name if call.name in self.tools.tools else "unknown",
                        outcome="SUCCEEDED" if result.success else "FAILED",
                        latency_ms=result.latency_ms,
                        error=result.error.code if result.error else None,
                    )
                else:
                    state.status = {
                        "FINAL_ANSWER": "ANSWER",
                        "CLARIFY": "CLARIFY",
                        "ABSTAIN": "ABSTAIN",
                    }[decision.action]
                    summary, interpretation = decision.reason, decision.interpretation
                event("STATE_UPDATED", state, transition=f"RUNNING->{state.status}")
            except ValueError:
                error = ErrorInfo(
                    code="INVALID_DECISION", message="Decision failed schema or business validation"
                )
                state.errors.append(error)
                state.observations.append(
                    ToolResult(tool_name="decision", success=False, error=error)
                )
                event("DECISION_MADE", state, outcome="INVALID", error=error.code)
                event("STATE_UPDATED", state, error=error.code, transition="RUNNING->RUNNING")
            except ExternalServiceError:
                state.status = "ERROR"
                state.errors.append(
                    ErrorInfo(
                        code="LLM_FAILURE",
                        message="Provider unavailable or malformed output",
                        retryable=True,
                    )
                )
                summary = "No fue posible obtener una decisión válida del provider."
                event("STATE_UPDATED", state, error="LLM_FAILURE", transition="RUNNING->ERROR")
            except Exception:
                state.status = "ERROR"
                state.errors.append(
                    ErrorInfo(code="INTERNAL_ERROR", message="Unexpected execution failure")
                )
                summary = "La ejecución terminó con un error técnico registrado."
                event("STATE_UPDATED", state, error="INTERNAL_ERROR", transition="RUNNING->ERROR")
        previous_status = state.status
        if state.status == "RUNNING":
            state.status = "ABSTAIN"
            state.missing_information.append("Límite de pasos alcanzado")
        result = build_report(state, summary, interpretation, self.stale_after_days)
        event("STATE_UPDATED", state, transition=f"{previous_status}->{state.status}")
        if result.status == "ABSTAIN":
            event("AGENT_ABSTAINED", state)
        event("AGENT_FINISHED", state)
        try:
            self.repository.save(state, result)
        except Exception:
            previous_status = state.status
            state.status = "ERROR"
            result.status = "ERROR"
            result.errors.append(
                ErrorInfo(code="PERSISTENCE_FAILURE", message="Could not persist execution")
            )
            event(
                "STATE_UPDATED",
                state,
                error="PERSISTENCE_FAILURE",
                transition=f"{previous_status}->ERROR",
            )
            event("AGENT_FINISHED", state, error="PERSISTENCE_FAILURE")
        return result
