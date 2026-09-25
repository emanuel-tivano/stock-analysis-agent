from unittest.mock import Mock

import pytest

from merval_agent.adapters.llm.fake import FakeLLMProvider
from merval_agent.domain.models import AgentDecision
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


@pytest.mark.parametrize(
    "ticker,name",
    [("EDN", "Edenor"), ("METR", "Metrogas"), ("BYMA", "Bolsas Y Mercados Argentinos")],
)
def test_llm_proposal_outside_catalog_is_validated_by_provider(make_agent, ticker, name):
    agent, repo = make_agent(validation_quotes={ticker: name})

    result = agent.run(f"Analizá técnicamente {ticker}")
    state = repo.records[0][0]

    assert result.status == "ANSWER"
    assert state.resolved_asset.status == "RESOLVED"
    assert state.resolved_asset.ticker == ticker
    assert state.resolved_asset.validation_method == "provider_quote"
    assert state.resolved_asset.validation_status == "VALIDATED"
    assert repo.market_paths.count(f"/api/stocks/{ticker}/quote") == 1
    resolved = next(event for event in state.trace_events if event["event"] == "ASSET_RESOLVED")
    assert resolved["proposed_symbol"] == ticker
    assert resolved["validation_method"] == "provider_quote"


def test_semantic_company_proposal_is_separate_from_validation(make_agent):
    fallback = FakeLLMProvider()

    def script(state):
        if not state.observations:
            return AgentDecision(
                action="CALL_TOOL",
                tool_name="resolve_asset",
                tool_args={
                    "query": state.user_request,
                    "symbol": "EDN",
                    "market": "bCBA",
                    "company_name": "Edenor",
                },
                intent={"analysis_type": "technical"},
                reason="Semantic proposal",
                confidence=1,
            )
        return fallback.decide(state, [])

    agent, repo = make_agent(provider=FakeLLMProvider(script), validation_quotes={"EDN": "Edenor"})
    result = agent.run("Analizá técnicamente Edenor")

    assert result.status == "ANSWER"
    assert repo.records[0][0].resolved_asset.ticker == "EDN"


@pytest.mark.parametrize(
    "message,ticker,name",
    [
        ("Analizá técnicamente Telecom", "TECO2", "Telecom Argentina"),
        ("Analizá técnicamente TECO2", "TECO2", "Telecom Argentina"),
        ("Analizá técnicamente TGNO4", "TGNO4", "Transportadora Gas Del Norte"),
        ("Analizá técnicamente TGSU2", "TGSU2", "Transportadora Gas Del Sur"),
        ("Analizá técnicamente A3", "A3", "Matba Rofex S.A."),
    ],
)
def test_domestic_equities_with_numeric_suffix_reach_analysis(make_agent, message, ticker, name):
    fallback = FakeLLMProvider()

    def script(state):
        if not state.observations and ticker == "TECO2" and "Telecom" in state.user_request:
            return AgentDecision(
                action="CALL_TOOL",
                tool_name="resolve_asset",
                tool_args={
                    "query": state.user_request,
                    "symbol": "TECO2",
                    "market": "bCBA",
                    "company_name": "Telecom Argentina",
                },
                intent={"analysis_type": "technical"},
                reason="Semantic Telecom proposal",
                confidence=1,
            )
        return fallback.decide(state, [])

    agent, repo = make_agent(provider=FakeLLMProvider(script), validation_quotes={ticker: name})
    result = agent.run(message)
    state = repo.records[0][0]

    assert result.status == "ANSWER"
    assert result.ticker == ticker
    assert state.resolved_asset.status == "RESOLVED"
    assert state.resolved_asset.existence_status == "CONFIRMED"
    assert state.resolved_asset.eligibility_status == "ELIGIBLE"
    assert state.resolved_asset.validation_method == "provider_quote"
    assert repo.market_paths.count(f"/api/stocks/{ticker}/quote") == 1
    assert f"/api/stocks/{ticker}/history" in repo.market_paths
    resolved = next(event for event in state.trace_events if event["event"] == "ASSET_RESOLVED")
    assert resolved["proposed_symbol"] == ticker
    assert resolved["proposed_market"] == "bCBA"
    assert resolved["existence_status"] == "CONFIRMED"
    assert resolved["eligibility_status"] == "ELIGIBLE"


def test_invalid_ticker_format_does_not_claim_provider_not_found(make_agent):
    agent, repo = make_agent()
    result = agent.run("Analizá técnicamente TECO22")
    resolution = repo.records[0][0].resolved_asset

    assert result.status == "CLARIFY"
    assert resolution.status == "NOT_FOUND"
    assert resolution.validation_status == "INVALID_FORMAT"
    assert resolution.existence_status == "NOT_VERIFIED"
    assert repo.market_paths == []
    assert "no tiene un formato válido" in result.executive_summary
    assert "proveedor" not in result.executive_summary.casefold()


def test_byma_market_context_does_not_replace_explicit_ticker(make_agent):
    agent, repo = make_agent()
    result = agent.run("Analizá técnicamente GGAL en BYMA")

    assert result.status == "ANSWER"
    assert repo.records[0][0].resolved_asset.ticker == "GGAL"


def test_llm_proposal_cannot_hide_multiple_explicit_tickers(make_agent):
    agent, repo = make_agent(
        provider=FakeLLMProvider(
            lambda state: AgentDecision(
                action="CALL_TOOL",
                tool_name="resolve_asset",
                tool_args={"query": state.user_request, "symbol": "GGAL", "market": "bCBA"},
                intent={"analysis_type": "technical"},
                reason="Overconfident proposal",
                confidence=1,
            )
        )
    )

    result = agent.run("Compará técnicamente GGAL y BYMA")

    assert result.status == "CLARIFY"
    assert repo.records[0][0].resolved_asset.status == "AMBIGUOUS"
    assert repo.records[0][0].resolved_asset.alternatives == ["GGAL", "BYMA"]


def test_invented_proposal_requires_authoritative_not_found(make_agent):
    agent, repo = make_agent()
    result = agent.run("Analizá técnicamente FAKEQ")
    state = repo.records[0][0]

    assert result.status == "CLARIFY"
    assert state.resolved_asset.status == "NOT_FOUND"
    assert state.resolved_asset.validation_method == "provider_quote"
    assert state.resolved_asset.validation_status == "NOT_FOUND"
    assert state.technical_data is None


def test_cedear_is_not_accepted_as_local_equity(make_agent):
    agent, repo = make_agent(validation_quotes={"AAPL": "Cedear Apple Inc."})
    result = agent.run("Analizá técnicamente AAPL")
    state = repo.records[0][0]

    assert result.status == "ABSTAIN"
    assert state.resolved_asset.status == "UNSUPPORTED"
    assert state.resolved_asset.ticker == "AAPL"
    assert state.resolved_asset.validation_status == "UNSUPPORTED"
    assert state.resolved_asset.existence_status == "CONFIRMED"
    assert state.resolved_asset.eligibility_status == "UNSUPPORTED"
    assert state.resolved_asset.eligibility_reason == "CEDEAR"
    assert result.technical.status == "UNSUPPORTED_ASSET"
    assert result.ticker == "AAPL"
    assert state.technical_data is None
    presented = present_analysis(result)
    assert presented.result_type == "unsupported_asset"
    assert presented.heading == "Instrumento fuera de alcance"
    assert presented.indicators == []
    event = next(
        event for event in state.trace_events if event["event"] == "ASSET_RESOLUTION_FAILED"
    )
    assert event["existence_status"] == "CONFIRMED"
    assert event["eligibility_status"] == "UNSUPPORTED"
    assert event["eligibility_reason"] == "CEDEAR"


def test_explicit_foreign_market_is_out_of_scope_without_market_lookup(make_agent):
    fallback = FakeLLMProvider()

    def script(state):
        if not state.observations:
            return AgentDecision(
                action="CALL_TOOL",
                tool_name="resolve_asset",
                tool_args={"query": state.user_request, "symbol": "AAPL", "market": "NASDAQ"},
                intent={"analysis_type": "technical"},
                reason="Foreign equity proposal",
                confidence=1,
            )
        return fallback.decide(state, [])

    agent, repo = make_agent(provider=FakeLLMProvider(script))
    result = agent.run("Analizá técnicamente AAPL en NASDAQ")
    resolution = repo.records[0][0].resolved_asset

    assert result.status == "ABSTAIN"
    assert resolution.status == "UNSUPPORTED"
    assert resolution.ticker == "AAPL"
    assert resolution.existence_status == "NOT_VERIFIED"
    assert resolution.eligibility_reason == "FOREIGN_MARKET"
    assert repo.market_paths == []


def test_semantic_cedear_proposal_is_rejected_after_provider_identification(make_agent):
    fallback = FakeLLMProvider()

    def script(state):
        if not state.observations:
            return AgentDecision(
                action="CALL_TOOL",
                tool_name="resolve_asset",
                tool_args={
                    "query": state.user_request,
                    "symbol": "AAPL",
                    "market": "bCBA",
                    "company_name": "Apple",
                },
                intent={"analysis_type": "technical"},
                reason="CEDEAR proposal",
                confidence=1,
            )
        return fallback.decide(state, [])

    agent, repo = make_agent(
        provider=FakeLLMProvider(script), validation_quotes={"AAPL": "Cedear Apple Inc."}
    )
    result = agent.run("Analizá el CEDEAR de Apple")
    state = repo.records[0][0]

    assert result.status == "ABSTAIN"
    assert state.resolved_asset.status == "UNSUPPORTED"
    assert state.resolved_asset.existence_status == "CONFIRMED"
    assert state.resolved_asset.eligibility_reason == "CEDEAR"
    assert repo.market_paths == ["/api/stocks/AAPL/quote"]


def test_provider_failure_during_resolution_is_not_not_found(make_agent):
    agent, repo = make_agent(validation_status=503)
    result = agent.run("Analizá técnicamente EDN")
    state = repo.records[0][0]

    assert result.status == "ERROR"
    assert state.resolved_asset is None
    assert state.observations[0].error.code == "EXTERNAL_SERVICE"
    assert state.observations[0].error_kind == "HTTP_503"
    assert "no se lo clasificó como inexistente" in result.executive_summary
