from typing import Protocol

from merval_agent.domain.models import AgentDecision, AgentState


class LLMProvider(Protocol):
    def decide(self, state: AgentState, tools: list[dict]) -> AgentDecision | dict: ...
