from typing import Any, Literal, Protocol
from uuid import UUID

from merval_agent.domain.actions import (
    ActionDecisionResponse,
    ApproveActionRequest,
    PendingAction,
)
from merval_agent.domain.models import AgentState, FinalAnalysis


class AnalysisRepository(Protocol):
    def save(
        self,
        state: AgentState,
        result: FinalAnalysis,
        *,
        pending_action: PendingAction | None = None,
    ) -> None: ...

    def get_action(self, action_id: UUID, session_id: str) -> ActionDecisionResponse: ...

    def decide_action(
        self,
        action_id: UUID,
        decision: Literal["approve", "modify", "reject"],
        request: ApproveActionRequest,
    ) -> ActionDecisionResponse: ...

    def get_action_events(self, action_id: UUID, session_id: str) -> list[dict[str, Any]]: ...

    def consume_rate_limit(
        self,
        client_key: str,
        bucket: str,
        window_start: int,
        limit: int,
        expires_before: int,
    ) -> bool: ...
