import logging

from merval_agent.adapters.llm.fake import FakeLLMProvider
from merval_agent.domain.models import AgentDecision


def names(repo):
    return [c.name for c in repo.records[-1][0].tool_calls]


def test_technical_does_not_call_fundamentals(make_agent):
    agent, repo = make_agent()
    result = agent.run("Analizá técnicamente GGAL")
    assert result.status == "ANSWER"
    assert result.technical.metrics.sma20 is not None
    assert result.fundamental.status == "NOT_REQUESTED"
    assert names(repo) == [
        "resolve_asset",
        "get_market_history",
        "calculate_technical_indicators",
        "search_methodology",
    ]
    assert result.trace_id


def test_fundamental_abstains_without_technical(make_agent):
    agent, repo = make_agent()
    result = agent.run("Evaluá los fundamentos de PAMP según Graham")
    assert result.status == "ABSTAIN"
    assert result.technical.status == "NOT_REQUESTED"
    assert names(repo) == ["resolve_asset", "get_latest_financial_statement", "search_methodology"]


def test_full_partial_and_bank_limitations(make_agent):
    agent, repo = make_agent()
    result = agent.run("Analizá GGAL")
    assert result.status == "ANSWER"
    assert result.fundamental.status == "INSUFFICIENT_DATA"
    assert any("financiera" in text for text in result.fundamental.limitations)
    assert "get_latest_financial_statement" in names(repo)


def test_ambiguous_and_unknown(make_agent):
    for message in ("Analizá Galicia", "Analizá XXXX"):
        agent, repo = make_agent()
        assert agent.run(message).status == "CLARIFY"
        assert names(repo) == ["resolve_asset"]


def test_max_steps(make_agent):
    provider = FakeLLMProvider(
        lambda s: AgentDecision(
            action="CALL_TOOL",
            tool_name="resolve_asset",
            tool_args={"query": "GGAL"},
            reason="repeat",
            confidence=1,
        )
    )
    agent, repo = make_agent(provider=provider, max_steps=3)
    result = agent.run("GGAL")
    assert result.status == "ABSTAIN"
    assert repo.records[0][0].iteration_count == 3
    assert "Límite de pasos alcanzado" in result.data_quality.missing_information


def test_invalid_decision_reaches_limit(make_agent):
    agent, repo = make_agent(provider=FakeLLMProvider(lambda s: {"action": "BUY"}), max_steps=2)
    result = agent.run("GGAL")
    assert result.status == "ABSTAIN"
    assert len(result.errors) == 2
    assert result.errors[0].code == "INVALID_DECISION"


def test_external_error_observed_and_abstains(make_agent):
    agent, repo = make_agent(market_status=429)
    result = agent.run("Técnico GGAL")
    assert result.status == "ABSTAIN"
    assert result.errors[0].code == "EXTERNAL_SERVICE"
    assert "calculate_technical_indicators" not in names(repo)


def test_demo_and_empty_never_answer(make_agent, payload):
    for data in (
        {**payload, "meta": {"source": "demo"}},
        {**payload, "data": []},
        {**payload, "meta": {"stale": True, "source": "live"}},
    ):
        agent, _ = make_agent(data=data)
        assert agent.run("Técnico GGAL").status == "ABSTAIN"


def test_demo_corpus_cannot_support_murphy_claim(make_agent):
    agent, _ = make_agent()
    result = agent.run("Analizá GGAL usando Murphy")
    assert result.status == "ABSTAIN"
    assert any("metodológicas" in m for m in result.data_quality.missing_information)


def test_provider_can_choose_methodology_before_market(make_agent):
    decisions = [
        {
            "action": "CALL_TOOL",
            "tool_name": "resolve_asset",
            "tool_args": {"query": "GGAL"},
            "intent": {"analysis_type": "technical"},
        },
        {
            "action": "CALL_TOOL",
            "tool_name": "search_methodology",
            "tool_args": {"query": "tendencia", "source": "murphy"},
        },
        {
            "action": "CALL_TOOL",
            "tool_name": "get_market_history",
            "tool_args": {"ticker": "GGAL", "range": "6M"},
        },
        {
            "action": "CALL_TOOL",
            "tool_name": "calculate_technical_indicators",
            "tool_args": {"ticker": "GGAL"},
        },
        {"action": "FINAL_ANSWER"},
    ]
    provider = FakeLLMProvider(
        lambda s: {"reason": "state-driven", "confidence": 1, **decisions[s.iteration_count - 1]}
    )
    agent, repo = make_agent(provider=provider)
    assert agent.run("Técnico GGAL").status == "ANSWER"
    assert names(repo)[1:3] == ["search_methodology", "get_market_history"]


def test_business_guard_rejects_unnecessary_tool(make_agent):
    def script(state):
        return {
            "action": "CALL_TOOL",
            "reason": "test",
            "confidence": 1,
            "intent": {"analysis_type": "technical"},
            "tool_name": "resolve_asset"
            if state.iteration_count == 1
            else "get_latest_financial_statement",
            "tool_args": {"query": "GGAL"} if state.iteration_count == 1 else {"ticker": "GGAL"},
        }

    agent, repo = make_agent(provider=FakeLLMProvider(script), max_steps=2)
    result = agent.run("Técnico GGAL")
    assert result.errors[0].code == "INVALID_TOOL_CALL"
    assert not repo.records[0][0].observations[-1].success


def test_structured_logging_excludes_request(make_agent, caplog):
    agent, _ = make_agent()
    with caplog.at_level(logging.INFO, logger="merval_agent"):
        agent.run("Técnico GGAL secret-test-123")
    assert "secret-test-123" not in caplog.text
    for name in (
        "AGENT_STARTED",
        "DECISION_MADE",
        "TOOL_STARTED",
        "TOOL_SUCCEEDED",
        "STATE_UPDATED",
        "AGENT_FINISHED",
    ):
        assert name in caplog.text


def test_observation_drives_retry_with_longer_range(make_agent, payload):
    agent, repo = make_agent()
    original = agent.tools.tools["get_market_history"].handler

    def history(args, state):
        result = original(args, state)
        if args.range == "1W":
            result["bars"] = result["bars"][-5:]
        return result

    agent.tools.tools["get_market_history"].handler = history

    def script(state):
        base = {"reason": "choose from evidence", "confidence": 1}
        if not state.resolved_asset:
            return {
                **base,
                "action": "CALL_TOOL",
                "intent": {"analysis_type": "technical"},
                "tool_name": "resolve_asset",
                "tool_args": {"query": "GGAL"},
            }
        if not state.technical_data or (
            state.technical_metrics and state.technical_metrics.sma20 is None
        ):
            return {
                **base,
                "action": "CALL_TOOL",
                "tool_name": "get_market_history",
                "tool_args": {
                    "ticker": "GGAL",
                    "range": "1W" if state.technical_data is None else "6M",
                },
            }
        if state.technical_metrics is None:
            return {
                **base,
                "action": "CALL_TOOL",
                "tool_name": "calculate_technical_indicators",
                "tool_args": {"ticker": "GGAL"},
            }
        return {**base, "action": "FINAL_ANSWER"}

    agent.provider = FakeLLMProvider(script)
    assert agent.run("Técnico GGAL").status == "ANSWER"
    state = repo.records[-1][0]
    assert [c.arguments["range"] for c in state.tool_calls if c.name == "get_market_history"] == [
        "1W",
        "6M",
    ]


def test_changing_asset_clears_old_evidence(make_agent):
    from merval_agent.agents.state import reduce_observation
    from merval_agent.domain.models import ToolResult
    from merval_agent.tools.assets import resolve_asset

    agent, repo = make_agent()
    agent.run("Técnico GGAL")
    state = repo.records[-1][0]
    assert state.technical_metrics is not None
    reduce_observation(
        state,
        ToolResult(
            tool_name="resolve_asset", success=True, data=resolve_asset("PAMP").model_dump()
        ),
    )
    assert state.technical_data is None
    assert state.technical_metrics is None
    assert state.resolved_asset.ticker == "PAMP"
