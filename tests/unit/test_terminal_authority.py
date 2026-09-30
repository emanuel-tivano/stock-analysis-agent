from copy import deepcopy
from datetime import UTC, datetime

import pytest

from merval_agent.adapters.llm.fake import FakeLLMProvider
from merval_agent.adapters.market_tracker import normalize_history
from merval_agent.agents.decisions import resolve_effective_terminal_action
from merval_agent.agents.report import build_report
from merval_agent.domain.models import (
    AgentState,
    Bar,
    QuoteSnapshot,
    TechnicalAssessment,
    UserIntent,
)


def terminal_technical_provider(action, captured=None):
    def decide(state):
        common = {"reason": "Model proposed abstention", "confidence": 1}
        if state.resolved_asset is None:
            return {
                **common,
                "action": "CALL_TOOL",
                "intent": {"analysis_type": "technical"},
                "tool_name": "resolve_asset",
                "tool_args": {"query": "GGAL"},
            }
        if state.technical_data is None:
            return {
                **common,
                "action": "CALL_TOOL",
                "tool_name": "get_market_history",
                "tool_args": {"ticker": "GGAL", "range": "6M"},
            }
        if state.technical_metrics is None:
            return {
                **common,
                "action": "CALL_TOOL",
                "tool_name": "calculate_technical_indicators",
                "tool_args": {"ticker": "GGAL"},
            }
        if captured is not None:
            captured["metrics"] = state.technical_metrics.model_copy(deep=True)
            captured["assessment"] = state.technical_assessment.model_copy(deep=True)
        return {
            **common,
            "action": action,
            "missing_information": ["Model claimed evidence was missing"],
        }

    return FakeLLMProvider(decide)


def abstaining_technical_provider(captured=None):
    return terminal_technical_provider("ABSTAIN", captured)


def clarifying_technical_provider(captured=None):
    return terminal_technical_provider("CLARIFY", captured)


def state_with_assessment(status, *, request="Técnico GGAL", intent="technical"):
    return AgentState(
        user_request=request,
        intent=UserIntent(analysis_type=intent),
        technical_assessment=TechnicalAssessment(status=status) if status else None,
    )


def test_complete_provisional_assessment_overrides_model_abstain_without_mutation(
    make_agent, payload
):
    captured = {}
    agent, repo = make_agent(provider=abstaining_technical_provider(captured))
    history_payload = deepcopy(payload)
    quote_row = history_payload["data"].pop()
    received_at = datetime.fromisoformat(history_payload["fetchedAt"]).astimezone(UTC)
    history = normalize_history(
        history_payload,
        "GGAL",
        "6M",
        "https://market.test/history",
        received_at=received_at,
    )
    quote = QuoteSnapshot(
        bar=Bar.model_validate({k: v for k, v in quote_row.items() if k != "currency"}),
        source="https://market.test/quote",
        observed_at=history.fetched_at,
        received_at=history.received_at,
        currency=history.currency,
    )
    history = history.model_copy(
        update={
            "bars": [*history.bars, quote.bar],
            "quote": quote,
            "enrichment_status": "appended",
        }
    )
    agent.tools.tools["get_market_history"].handler = lambda args, state: history.model_dump(
        mode="json"
    )

    result = agent.run("Analizá técnicamente GGAL")
    state = repo.records[0][0]

    assert result.status == "ANSWER"
    assert captured["assessment"].status == "COMPLETE"
    assert captured["assessment"].basis.quote_in_indicators
    assert result.technical.metrics == captured["metrics"]
    assert result.technical.assessment == captured["assessment"]
    assert result.data_quality.missing_information == []
    override = next(e for e in state.trace_events if e["event"] == "TERMINAL_ACTION_OVERRIDDEN")
    assert {
        key: override[key]
        for key in (
            "proposed_action",
            "effective_action",
            "override_reason",
            "assessment_status",
        )
    } == {
        "proposed_action": "ABSTAIN",
        "effective_action": "FINAL_ANSWER",
        "override_reason": "TECHNICAL_ASSESSMENT_ANSWERABLE",
        "assessment_status": "COMPLETE",
    }
    assert state.trace_events[-1]["final_reason"] == "AVAILABLE_DATA_WITH_LIMITATIONS"


@pytest.mark.parametrize(
    ("sample_size", "expected_status"),
    [(60, "COMPLETE"), (34, "PARTIAL")],
)
def test_answerable_provisional_assessment_overrides_model_clarify_without_mutation(
    make_agent, payload, sample_size, expected_status
):
    captured = {}
    agent, repo = make_agent(provider=clarifying_technical_provider(captured))
    history_payload = deepcopy(payload)
    history_payload["data"] = history_payload["data"][-sample_size:]
    quote_row = history_payload["data"].pop()
    received_at = datetime.fromisoformat(history_payload["fetchedAt"]).astimezone(UTC)
    history = normalize_history(
        history_payload,
        "GGAL",
        "6M",
        "https://market.test/history",
        received_at=received_at,
    )
    quote = QuoteSnapshot(
        bar=Bar.model_validate({k: v for k, v in quote_row.items() if k != "currency"}),
        source="https://market.test/quote",
        observed_at=history.fetched_at,
        received_at=history.received_at,
        currency=history.currency,
    )
    history = history.model_copy(
        update={
            "bars": [*history.bars, quote.bar],
            "quote": quote,
            "enrichment_status": "appended",
        }
    )
    agent.tools.tools["get_market_history"].handler = lambda args, state: history.model_dump(
        mode="json"
    )

    result = agent.run("Analizá técnicamente GGAL")
    state = repo.records[0][0]

    assert result.status == "ANSWER"
    assert captured["assessment"].status == expected_status
    assert captured["assessment"].basis.quote_in_indicators
    assert result.technical.metrics == captured["metrics"]
    assert result.technical.assessment == captured["assessment"]
    assert result.data_quality.missing_information == []
    override = next(e for e in state.trace_events if e["event"] == "TERMINAL_ACTION_OVERRIDDEN")
    assert {
        key: override[key]
        for key in (
            "proposed_action",
            "effective_action",
            "override_reason",
            "assessment_status",
        )
    } == {
        "proposed_action": "CLARIFY",
        "effective_action": "FINAL_ANSWER",
        "override_reason": "TECHNICAL_ASSESSMENT_ANSWERABLE",
        "assessment_status": expected_status,
    }
    assert state.trace_events[-1]["final_reason"] == "AVAILABLE_DATA_WITH_LIMITATIONS"


def test_partial_answerable_assessment_overrides_model_abstain(make_agent, payload):
    partial = deepcopy(payload)
    partial["data"] = partial["data"][-34:]
    agent, repo = make_agent(provider=abstaining_technical_provider(), data=partial)

    result = agent.run("Analizá técnicamente GGAL")

    assert result.status == "ANSWER"
    assert result.technical.assessment.status == "PARTIAL"
    assert result.technical.assessment.conclusion != "UNAVAILABLE"
    assert any(e["event"] == "TERMINAL_ACTION_OVERRIDDEN" for e in repo.records[0][0].trace_events)


def test_insufficient_assessment_preserves_model_abstain(make_agent, payload):
    insufficient = deepcopy(payload)
    insufficient["data"] = insufficient["data"][-14:]
    agent, repo = make_agent(provider=abstaining_technical_provider(), data=insufficient)

    result = agent.run("Analizá técnicamente GGAL")

    assert result.status == "ABSTAIN"
    assert result.technical.assessment.status == "INSUFFICIENT_DATA"
    assert not any(
        e["event"] == "TERMINAL_ACTION_OVERRIDDEN" for e in repo.records[0][0].trace_events
    )
    assert repo.records[0][0].trace_events[-1]["final_reason"] == "INSUFFICIENT_EVIDENCE"


def test_insufficient_assessment_preserves_model_clarify(make_agent, payload):
    insufficient = deepcopy(payload)
    insufficient["data"] = insufficient["data"][-14:]
    agent, repo = make_agent(provider=clarifying_technical_provider(), data=insufficient)

    result = agent.run("Analizá técnicamente GGAL")

    assert result.status == "CLARIFY"
    assert result.technical.assessment.status == "INSUFFICIENT_DATA"
    assert not any(
        e["event"] == "TERMINAL_ACTION_OVERRIDDEN" for e in repo.records[0][0].trace_events
    )
    assert repo.records[0][0].trace_events[-1]["final_reason"] == "USER_INFORMATION_REQUIRED"


@pytest.mark.parametrize("terminal_status", ["ABSTAIN", "CLARIFY"])
def test_report_safety_net_reuses_terminal_policy(make_agent, terminal_status):
    agent, repo = make_agent()
    assert agent.run("Analizá técnicamente GGAL").status == "ANSWER"
    state = repo.records[0][0]
    state.status = terminal_status

    result = build_report(
        state,
        "Model proposed abstention",
        "",
        agent.stale_after_days,
        reference_time=state.technical_evaluated_at,
    )

    assert result.status == state.status == "ANSWER"
    assert result.technical.assessment.status == "COMPLETE"


@pytest.mark.parametrize(
    "status",
    ["INSUFFICIENT_DATA", "STALE", "INVALID_DATA", "UNVERIFIED", "SOURCE_ERROR"],
)
@pytest.mark.parametrize("proposed_action", ["ABSTAIN", "CLARIFY"])
def test_non_answerable_assessments_never_override_terminal_action(status, proposed_action):
    resolution = resolve_effective_terminal_action(proposed_action, state_with_assessment(status))
    assert resolution.effective_action == proposed_action
    assert resolution.override_reason is None


@pytest.mark.parametrize("proposed_action", ["ABSTAIN", "CLARIFY"])
def test_explicit_unsatisfied_methodology_never_overrides_terminal_action(proposed_action):
    state = state_with_assessment("COMPLETE", request="Técnico GGAL según Murphy")
    resolution = resolve_effective_terminal_action(proposed_action, state)
    assert resolution.effective_action == proposed_action


@pytest.mark.parametrize(
    "user_request,intent",
    [
        ("Análisis integral de GGAL", "full"),
        ("Análisis fundamental de GGAL", "fundamental"),
    ],
)
@pytest.mark.parametrize("proposed_action", ["ABSTAIN", "CLARIFY"])
def test_incomplete_nontechnical_requests_never_override_terminal_action(
    user_request, intent, proposed_action
):
    state = state_with_assessment("COMPLETE", request=user_request, intent=intent)
    resolution = resolve_effective_terminal_action(proposed_action, state)
    assert resolution.effective_action == proposed_action


def test_pre_evidence_intent_contradiction_preserves_clarify():
    state = state_with_assessment(
        None,
        request="Analizá técnicamente GGAL usando el balance",
        intent="technical",
    )

    resolution = resolve_effective_terminal_action("CLARIFY", state)

    assert resolution.effective_action == "CLARIFY"
    assert resolution.override_reason is None


def test_final_answer_is_never_rewritten_by_terminal_policy():
    resolution = resolve_effective_terminal_action(
        "FINAL_ANSWER", state_with_assessment("COMPLETE")
    )

    assert resolution.effective_action == "FINAL_ANSWER"
    assert resolution.override_reason is None
