from merval_agent.domain.errors import DecisionValidationError
from merval_agent.domain.models import AgentDecision, AgentState


def validate_decision(decision: AgentDecision, state: AgentState) -> None:
    if decision.intent and state.tool_calls and decision.intent != state.intent:
        raise DecisionValidationError("INTENT_CHANGE")
    if decision.action == "FINAL_ANSWER" and (
        not state.resolved_asset or not state.resolved_asset.ticker
    ):
        raise DecisionValidationError("UNRESOLVED_ASSET")
