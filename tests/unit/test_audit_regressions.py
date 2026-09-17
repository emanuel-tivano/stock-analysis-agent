import httpx
import pytest

from merval_agent.adapters.llm.compatible import CompatibleLLMProvider
from merval_agent.adapters.llm.fake import FakeLLMProvider
from merval_agent.domain.models import AgentDecision


@pytest.mark.parametrize("status,attempts", [(400, 1), (401, 1), (403, 1), (429, 2), (503, 2)])
def test_compatible_transport_retry_and_telemetry(make_agent, status, attempts):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={"error": "private upstream error"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        provider = CompatibleLLMProvider(http, "https://llm.test", "offline", "private")
        agent, repo = make_agent(provider=provider)
        result = agent.run("Tecnico GGAL")
    assert result.status == "ERROR" and result.errors[-1].code == "LLM_FAILURE"
    assert len(requests) == attempts
    assert result.errors[-1].retryable == (attempts == 2)
    failures = [e for e in repo.records[0][0].trace_events if e["event"] == "LLM_FAILED"]
    assert failures[-1]["http_status"] == status
    assert failures[-1]["retryable"] == (attempts == 2)
    assert "private upstream" not in str(failures)


@pytest.mark.parametrize("body", ["[]", "null", "42", "bad-json"])
def test_malformed_envelope_is_provider_failure_not_internal(make_agent, body):
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=body))
    ) as http:
        provider = CompatibleLLMProvider(http, "https://llm.test", "offline", "private")
        agent, _ = make_agent(provider=provider)
        result = agent.run("Tecnico GGAL")
    assert result.status == "ERROR" and result.errors[-1].code == "LLM_FAILURE"


@pytest.mark.parametrize("status", [403, 429, 503])
def test_unrecovered_market_failure_is_error(make_agent, status):
    agent, repo = make_agent(market_status=status)
    result = agent.run("Tecnico GGAL")
    assert result.status == "ERROR"
    assert result.errors[-1].code == "EXTERNAL_SERVICE"
    assert repo.records[0][0].trace_events[-1]["final_reason"] == "EXTERNAL_SERVICE"


def test_recovered_market_failure_can_answer(make_agent):
    from merval_agent.domain.errors import ExternalServiceError

    def script(state):
        step = state.iteration_count
        names = {
            1: "resolve_asset",
            2: "get_market_history",
            3: "get_market_history",
            4: "calculate_technical_indicators",
        }
        if step == 5:
            return AgentDecision(action="FINAL_ANSWER", reason="Recovered", confidence=1)
        return AgentDecision(
            action="CALL_TOOL",
            tool_name=names[step],
            tool_args={"query": "GGAL"}
            if step == 1
            else {"ticker": "GGAL", "range": "6M"}
            if step in (2, 3)
            else {"ticker": "GGAL"},
            reason="Fetch",
            confidence=1,
        )

    agent, repo = make_agent(provider=FakeLLMProvider(script))
    tool = agent.tools.tools["get_market_history"]
    original = tool.handler
    attempts = 0

    def flaky(*args):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            try:
                raise httpx.ReadTimeout("transient")
            except httpx.ReadTimeout as exc:
                raise ExternalServiceError("timeout") from exc
        return original(*args)

    tool.handler = flaky
    assert agent.run("Tecnico GGAL").status == "ANSWER"
    assert attempts == 2
    event = next(e for e in repo.records[0][0].trace_events if "market_data" in e)
    assert len(event["market_data"]["snapshot_sha256"]) == 64


@pytest.mark.parametrize(
    "later_tool,args,data",
    [
        ("resolve_asset", {"query": "Grupo GGAL"}, {"ticker": "GGAL", "confidence": 1}),
        ("search_methodology", {"source": "graham", "query": "value"}, {"evidence": []}),
    ],
)
def test_unrelated_success_does_not_hide_failure(later_tool, args, data):
    from merval_agent.agents.report import build_report
    from merval_agent.domain.models import AgentState, ErrorInfo, ToolCall, ToolResult

    state = AgentState(
        user_request="GGAL",
        status="ABSTAIN",
        tool_calls=[
            ToolCall(name="resolve_asset", arguments={"query": "GGAL"}),
            ToolCall(name="search_methodology", arguments={"source": "murphy", "query": "trend"}),
            ToolCall(name=later_tool, arguments=args),
        ],
        observations=[
            ToolResult(
                tool_name="resolve_asset", success=True, data={"ticker": "GGAL", "confidence": 1}
            ),
            ToolResult(
                tool_name="search_methodology",
                success=False,
                error=ErrorInfo(code="EXTERNAL_SERVICE", message="failed"),
            ),
            ToolResult(tool_name=later_tool, success=True, data=data),
        ],
    )
    assert build_report(state, "Missing", "", 7).status == "ERROR"
