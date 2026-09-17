import json

import httpx
import pytest

from merval_agent.adapters.llm.compatible import CompatibleLLMProvider
from merval_agent.adapters.llm.context import build_agent_context
from merval_agent.config import Settings
from merval_agent.domain.models import AgentState, ToolResult
from merval_agent.evaluation import aggregate


def decision(action="CLARIFY", **kwargs):
    return {"action": action, "reason": "Operational decision", "confidence": 1, **kwargs}


def provider(outputs, requests):
    def handler(request):
        requests.append(json.loads(request.content))
        output = outputs[min(len(requests) - 1, len(outputs) - 1)]
        if isinstance(output, int):
            return httpx.Response(output)
        if isinstance(output, Exception):
            raise output
        content = json.dumps(output) if isinstance(output, dict) else output
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        )

    return CompatibleLLMProvider(
        httpx.Client(transport=httpx.MockTransport(handler)),
        "https://llm.test/v1",
        "test-model",
        "private-key",
    )


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        'prefix {"action":"CLARIFY"}',
        "",
        {},
        decision("CALL_TOOL", tool_name="unknown"),
        decision(
            "CALL_TOOL", tool_name="get_market_history", tool_args={"ticker": "GGAL", "range": "6M"}
        ),
        decision(
            "CALL_TOOL", tool_name="calculate_technical_indicators", tool_args={"ticker": "GGAL"}
        ),
        429,
        503,
        httpx.ReadTimeout("private-error"),
    ],
)
def test_bounded_repair_and_private_trace(make_agent, bad):
    requests = []
    real = provider([bad, decision()], requests)
    agent, repo = make_agent(provider=real)
    result = agent.run("private-user-text")
    assert result.status == "CLARIFY"
    assert len(requests) == 2
    events = repo.records[0][0].trace_events
    assert sum(e["event"] == "LLM_STARTED" for e in events) == 2
    assert any(e["event"] == "LLM_SUCCEEDED" and e["usage"]["total_tokens"] == 30 for e in events)
    trace = json.dumps(events)
    assert (
        "private-key" not in trace
        and "private-user-text" not in trace
        and "private-error" not in trace
    )
    real.http.close()


def test_exhaustion_is_error(make_agent):
    requests = []
    real = provider([{}], requests)
    agent, _ = make_agent(provider=real)
    assert agent.run("GGAL").status == "ERROR"
    assert len(requests) == 2
    real.http.close()


def test_duplicate_success_rejected_and_observation_reused(make_agent):
    resolve = decision(
        "CALL_TOOL",
        tool_name="resolve_asset",
        tool_args={"query": "GGAL"},
        intent={"analysis_type": "technical"},
    )
    requests = []
    real = provider([resolve, resolve, decision("ABSTAIN")], requests)
    agent, repo = make_agent(provider=real)
    agent.run("Analizá técnicamente GGAL")
    state = repo.records[0][0]
    assert len(state.tool_calls) == 1
    assert any(e.get("duplicate_tool_call") for e in state.trace_events)
    context = json.loads(requests[1]["messages"][1]["content"])
    assert context["resolved_asset"]["ticker"] == "GGAL"
    assert context["observations"] == [["resolve_asset", True, None]]
    real.http.close()


def test_failed_tool_can_retry(make_agent):
    requests = []
    resolve = decision(
        "CALL_TOOL",
        tool_name="resolve_asset",
        tool_args={"query": "GGAL"},
        intent={"analysis_type": "technical"},
    )
    market = decision(
        "CALL_TOOL", tool_name="get_market_history", tool_args={"ticker": "GGAL", "range": "6M"}
    )
    real = provider([resolve, market, market, decision("ABSTAIN")], requests)
    agent, repo = make_agent(provider=real, market_status=503)
    agent.run("Analizá técnicamente GGAL")
    assert [c.name for c in repo.records[0][0].tool_calls].count("get_market_history") == 2
    assert not any(e.get("duplicate_tool_call") for e in repo.records[0][0].trace_events)
    real.http.close()


def test_forbidden_branch_never_executes(make_agent):
    requests = []
    real = provider(
        [
            decision(
                "CALL_TOOL",
                tool_name="resolve_asset",
                tool_args={"query": "GGAL"},
                intent={"analysis_type": "technical"},
            ),
            decision(
                "CALL_TOOL",
                tool_name="get_latest_financial_statement",
                tool_args={"ticker": "GGAL"},
            ),
            decision("ABSTAIN"),
        ],
        requests,
    )
    agent, repo = make_agent(provider=real)
    agent.run("Analizá técnicamente GGAL")
    assert [c.name for c in repo.records[0][0].tool_calls] == ["resolve_asset"]
    assert any(
        e.get("tool_name") == "get_latest_financial_statement"
        and e["event"] == "DECISION_VALIDATION_FAILED"
        for e in repo.records[0][0].trace_events
    )
    real.http.close()


def test_context_bounded_no_raw_observations():
    state = AgentState(
        user_request="x" * 10000,
        observations=[ToolResult(tool_name="x", success=True, data={"Authorization": "private"})]
        * 10000,
        missing_information=["x" * 10000] * 10000,
    )
    context = build_agent_context(state, [])
    serialized = json.dumps(context)
    assert len(serialized) < 4000
    assert "private" not in serialized and "Authorization" not in serialized
    assert context["objective_truncated"]


def test_metrics_empty_and_cost_unknown():
    metrics = aggregate([], Settings(_env_file=None))
    assert metrics["cost"] is None
    assert metrics["input_tokens"] is None
    assert metrics["case_count"] == 0


def test_model_prose_cannot_fabricate_financial_output(make_agent):
    requests = []
    real = provider(
        [
            decision(
                "CALL_TOOL",
                tool_name="resolve_asset",
                tool_args={"query": "PAMP"},
                intent={"analysis_type": "fundamental"},
            ),
            decision(
                "ABSTAIN",
                reason="BUY PAMP, ROE 99%; Graham authoritative",
                interpretation="EPS 200",
                missing_information=["SELL PAMP debt 300"],
            ),
        ],
        requests,
    )
    agent, _ = make_agent(provider=real)
    result = agent.run("Invent financial metrics")
    raw = result.model_dump_json()
    assert result.status == "ABSTAIN"
    assert all(
        x not in raw for x in ("BUY", "SELL", "ROE 99", "EPS 200", "debt 300", "authoritative")
    )
    real.http.close()


def test_structured_output_modes(make_agent):
    for mode in ("json_schema", "json_object", "none"):
        requests = []
        real = provider([decision()], requests)
        real.response_format = mode
        agent, _ = make_agent(provider=real)
        assert agent.run("Ambiguous").status == "CLARIFY"
        if mode == "none":
            assert "response_format" not in requests[0]
        else:
            assert requests[0]["response_format"]["type"] == mode
        real.http.close()
