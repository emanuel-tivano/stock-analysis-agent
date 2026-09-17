from unittest.mock import Mock

import pytest

from merval_agent.presentation.presenter import present_analysis
from merval_agent.tools.assets import resolve_asset


def tool_names(state):
    return [call.name for call in state.tool_calls]


@pytest.mark.parametrize(
    "message,requested",
    [
        ("Analizá técnicamente PPSA", "PPSA"),
        ("Analizá técnicamente XYZINVALIDO", "XYZINVALIDO"),
    ],
)
def test_unknown_asset_stops_before_market_history(make_agent, message, requested):
    agent, repo = make_agent()
    history = Mock(side_effect=AssertionError("market history must not be called"))
    agent.tools.tools["get_market_history"].handler = history

    result = agent.run(message)
    state = repo.records[0][0]
    presented = present_analysis(result)

    assert state.resolved_asset.status == "NOT_FOUND"
    assert state.resolved_asset.requested_symbol == requested
    assert tool_names(state) == ["resolve_asset"]
    assert history.call_count == 0
    assert state.technical_data is None
    assert state.technical_metrics is None
    assert state.technical_assessment is None
    assert result.status == "CLARIFY"
    assert result.technical.status == "ASSET_NOT_FOUND"
    assert result.technical.assessment is None
    assert result.technical.metrics is None
    assert requested in result.executive_summary
    assert "insuficiente" not in result.executive_summary.casefold()
    assert presented.result_type == "asset_not_found"
    assert presented.indicators == []
    assert presented.sources == []
    assert presented.technical_details is None
    event = next(
        event for event in state.trace_events if event["event"] == "ASSET_RESOLUTION_FAILED"
    )
    assert event["reason"] == "NOT_FOUND"
    assert event["requested_symbol"] == requested


def test_ambiguous_asset_stops_before_market_history(make_agent):
    agent, repo = make_agent()
    history = Mock(side_effect=AssertionError("market history must not be called"))
    agent.tools.tools["get_market_history"].handler = history

    result = agent.run("Grupo Financiero Galicia")
    state = repo.records[0][0]
    presented = present_analysis(result)

    assert state.resolved_asset.status == "AMBIGUOUS"
    assert state.resolved_asset.alternatives == [
        "GGAL (acción BYMA, ARS)",
        "GGAL (ADR NYSE, USD)",
    ]
    assert tool_names(state) == ["resolve_asset"]
    assert history.call_count == 0
    assert state.technical_assessment is None
    assert result.status == "CLARIFY"
    assert result.technical.status == "AMBIGUOUS_ASSET"
    assert result.technical.assessment is None
    assert result.executive_summary == (
        "El activo es ambiguo. Indicá el ticker exacto o especificá el instrumento "
        "y mercado que querés analizar."
    )
    assert presented.result_type == "ambiguous_asset"
    assert presented.indicators == []
    assert presented.technical_details is None


def test_supported_asset_with_short_history_remains_insufficient_data(make_agent, payload):
    short_payload = {**payload, "data": payload["data"][-10:]}
    agent, repo = make_agent(data=short_payload)
    original = agent.tools.tools["get_market_history"].handler
    history = Mock(wraps=original)
    agent.tools.tools["get_market_history"].handler = history

    result = agent.run("Analizá técnicamente GGAL")
    state = repo.records[0][0]
    presented = present_analysis(result)

    assert state.resolved_asset.status == "RESOLVED"
    assert state.resolved_asset.ticker == "GGAL"
    assert history.call_count == 1
    assert "get_market_history" in tool_names(state)
    assert state.technical_metrics.sample_size == 10
    assert result.status == "ABSTAIN"
    assert result.ticker == "GGAL"
    assert result.technical.status == "INSUFFICIENT_DATA"
    assert result.technical.assessment.status == "INSUFFICIENT_DATA"
    assert presented.result_type == "insufficient_market_data"
    assert presented.technical_details is not None
    assert presented.indicators
    assert "información suficiente" in presented.user_message


@pytest.mark.parametrize("ticker", ["GGAL", "PAMP"])
def test_supported_asset_normal_flow_is_unchanged(make_agent, ticker):
    agent, repo = make_agent()
    original = agent.tools.tools["get_market_history"].handler
    history = Mock(wraps=original)
    agent.tools.tools["get_market_history"].handler = history

    result = agent.run(f"Analizá técnicamente {ticker}")
    state = repo.records[0][0]

    assert state.resolved_asset.status == "RESOLVED"
    assert state.resolved_asset.ticker == ticker
    assert history.call_count == 1
    assert result.status == "ANSWER"
    assert result.ticker == ticker
    assert result.technical.metrics.sample_size == 60
    assert present_analysis(result).result_type == "successful_analysis"


def test_asset_resolver_exposes_explicit_domain_outcomes():
    assert resolve_asset("PPSA").status == "NOT_FOUND"
    assert resolve_asset("XYZINVALIDO").status == "NOT_FOUND"
    assert resolve_asset("Grupo Financiero Galicia").status == "AMBIGUOUS"
    assert resolve_asset("GGAL").status == "RESOLVED"
