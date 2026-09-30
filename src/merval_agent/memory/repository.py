from typing import Protocol

from merval_agent.domain.actions import PendingAction
from merval_agent.domain.models import AgentState, FinalAnalysis


class AnalysisRepository(Protocol):
    def save(
        self,
        state: AgentState,
        result: FinalAnalysis,
        *,
        pending_action: PendingAction | None = None,
    ) -> None: ...
