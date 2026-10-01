from collections.abc import Callable
from datetime import datetime

from merval_agent.domain.actions import digest
from merval_agent.domain.models import AgentState
from merval_agent.domain.technical_assessment import assess


def refresh_technical_snapshot(
    state: AgentState,
    previous_sha256: str | None,
    *,
    clock: Callable[[], datetime],
    stale_after_days: int,
    emit: Callable[..., None],
) -> str | None:
    if not state.resolved_asset or state.resolved_asset.status != "RESOLVED":
        state.technical_assessment = None
        state.technical_evaluated_at = None
        return None

    snapshot_sha256 = digest(
        {
            "history": state.technical_data.model_dump(mode="json")
            if state.technical_data
            else None,
            "metrics": state.technical_metrics.model_dump(mode="json")
            if state.technical_metrics
            else None,
        }
    )
    if (
        snapshot_sha256 == previous_sha256
        and state.technical_assessment is not None
        and state.technical_evaluated_at is not None
    ):
        return snapshot_sha256

    evaluated_at = clock()
    if evaluated_at.tzinfo is None:
        raise ValueError("Agent clock must return a timezone-aware datetime")
    state.technical_evaluated_at = evaluated_at
    state.technical_assessment = assess(
        state.technical_data,
        state.technical_metrics,
        evaluated_at,
        stale_after_days,
    )
    if state.technical_data:
        history = state.technical_data
        quote = history.quote
        emit(
            "TECHNICAL_ASSESSED",
            state,
            assessment_status=state.technical_assessment.status,
            provider_fetched_at=history.provider_fetched_at.isoformat(),
            received_at=history.received_at.isoformat(),
            evaluated_at=evaluated_at.isoformat(),
            provider_clock_skew_ms=(
                history.provider_fetched_at - history.received_at
            ).total_seconds()
            * 1000,
            quote_observed_at=quote.observed_at.isoformat() if quote else None,
            quote_provider_fetched_at=(
                quote.provider_fetched_at.isoformat()
                if quote and quote.provider_fetched_at
                else None
            ),
            quote_received_at=quote.received_at.isoformat() if quote else None,
            quote_provider_clock_skew_ms=(
                (quote.provider_fetched_at - quote.received_at).total_seconds() * 1000
                if quote and quote.provider_fetched_at
                else None
            ),
        )
    return snapshot_sha256
