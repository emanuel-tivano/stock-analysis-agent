from merval_agent.domain.errors import DecisionValidationError
from merval_agent.domain.models import AgentDecision, AgentState

from .intent import explicit_analysis_type


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
