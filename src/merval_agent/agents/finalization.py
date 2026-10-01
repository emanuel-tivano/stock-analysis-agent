from collections.abc import Callable

from merval_agent.domain.actions import EvidenceSnapshot, PendingAction, digest, requests_review
from merval_agent.domain.models import AgentState, ErrorInfo, FinalAnalysis
from merval_agent.domain.technical_assessment import is_answerable
from merval_agent.memory.repository import AnalysisRepository

from .report import build_report, describe_generation


def finalize_run(
    state: AgentState,
    *,
    message: str,
    summary: str,
    interpretation: str,
    stale_after_days: int,
    degraded: bool,
    repository: AnalysisRepository,
    emit: Callable[..., None],
) -> FinalAnalysis:
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
        stale_after_days,
        reference_time=state.technical_evaluated_at,
    )
    result.generation = describe_generation(state.trace_events, result.status, degraded)
    if result.generation.mode == "DETERMINISTIC_FALLBACK":
        result.technical.limitations.extend(result.generation.warnings)
    if previous_status != "ERROR" or state.status != "ERROR":
        emit("STATE_UPDATED", state, transition=f"{previous_status}->{state.status}")
    if result.status == "ABSTAIN":
        emit("AGENT_ABSTAINED", state)

    pending_action = _pending_review(state, result, message)
    emit(
        "AGENT_FINISHED",
        state,
        generation=result.generation.model_dump(mode="json"),
        evaluated_at=(
            state.technical_evaluated_at.isoformat() if state.technical_evaluated_at else None
        ),
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
            repository.save(state, result, pending_action=pending_action)
        else:
            repository.save(state, result)
    except Exception:
        previous_status = state.status
        state.status = "ERROR"
        result.status = "ERROR"
        result.pending_action = None
        result.errors.append(
            ErrorInfo(code="PERSISTENCE_FAILURE", message="Could not persist execution")
        )
        emit(
            "STATE_UPDATED",
            state,
            error="PERSISTENCE_FAILURE",
            **({"transition": f"{previous_status}->ERROR"} if previous_status != "ERROR" else {}),
        )
        emit("AGENT_FINISHED", state, error="PERSISTENCE_FAILURE")
    return result


def _pending_review(
    state: AgentState,
    result: FinalAnalysis,
    message: str,
) -> PendingAction | None:
    if not (
        requests_review(message)
        and result.status == "ANSWER"
        and result.analysis_type == "technical"
        and is_answerable(result.technical.assessment)
        and state.technical_data
    ):
        return None
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
    result.executive_summary = "Borrador preparado para revisión; todavía no se finalizó el informe."
    return pending_action
