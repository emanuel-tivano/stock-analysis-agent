import re
from dataclasses import dataclass
from typing import Literal

from merval_agent.domain.errors import DecisionValidationError
from merval_agent.domain.models import AgentDecision, AgentState
from merval_agent.domain.technical_assessment import is_answerable

from .intent import explicit_analysis_type, explicit_full_request

TerminalAction = Literal["CLARIFY", "FINAL_ANSWER", "ABSTAIN"]


@dataclass(frozen=True)
class TerminalActionResolution:
    proposed_action: TerminalAction
    effective_action: TerminalAction
    override_reason: str | None = None


def explicit_methodology_requested(state: AgentState) -> bool:
    return bool(re.search(r"\b(?:murphy|graham)\b", state.user_request, re.I))


def explicit_methodology_pending(state: AgentState) -> bool:
    return explicit_methodology_requested(state) and not any(
        evidence.kind == "METHODOLOGY" for evidence in state.methodology_evidence
    )


def resolve_effective_terminal_action(
    proposed_action: TerminalAction, state: AgentState
) -> TerminalActionResolution:
    """Keep terminal authority with deterministic evidence rules, not model preference."""
    unsupported_full = (
        explicit_full_request(state.user_request)
        and explicit_analysis_type(state.user_request) != "technical"
    )
    if (
        proposed_action == "ABSTAIN"
        and state.intent.analysis_type == "technical"
        and not unsupported_full
        and is_answerable(state.technical_assessment)
        and not explicit_methodology_pending(state)
    ):
        return TerminalActionResolution(
            proposed_action=proposed_action,
            effective_action="FINAL_ANSWER",
            override_reason="TECHNICAL_ASSESSMENT_ANSWERABLE",
        )
    return TerminalActionResolution(
        proposed_action=proposed_action,
        effective_action=proposed_action,
    )


def validate_decision(decision: AgentDecision, state: AgentState) -> None:
    requested = explicit_analysis_type(state.user_request)
    if (
        decision.action in ("CALL_TOOL", "FINAL_ANSWER")
        and decision.intent
        and requested
        and decision.intent.analysis_type != requested
    ):
        raise DecisionValidationError("INTENT_CHANGE")
    if decision.intent and state.tool_calls and decision.intent != state.intent:
        raise DecisionValidationError("INTENT_CHANGE")
    if decision.action == "FINAL_ANSWER" and (
        not state.resolved_asset or not state.resolved_asset.ticker
    ):
        raise DecisionValidationError("UNRESOLVED_ASSET")
