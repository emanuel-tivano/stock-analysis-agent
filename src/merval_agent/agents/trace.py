import json
import logging

from merval_agent.domain.models import AgentState

logger = logging.getLogger("merval_agent")


def event(name: str, state: AgentState, **fields) -> None:
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
        },
        **fields,
    }
    state.trace_events.append(record)
    logger.info(json.dumps(record))
