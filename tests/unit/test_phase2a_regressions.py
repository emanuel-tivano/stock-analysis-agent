import json

import httpx
import pytest

from merval_agent.adapters.llm.fake import FakeLLMProvider
from merval_agent.adapters.llm.gemini import GeminiLLMProvider
from merval_agent.agents.intent import explicit_analysis_type
from merval_agent.domain.errors import ExternalServiceError
from merval_agent.domain.models import AgentState


@pytest.mark.parametrize(
    "message,expected",
    [
        ("Analiz\u00e1 t\u00e9cnicamente GGAL", "technical"),
        ("AN\u00c1LISIS T\u00c9CNICO GGAL", "technical"),
        ("Quiero una evaluaci\u00f3n t\u00e9cnica de GGAL", "technical"),
        ("Analiz\u00e1 los fundamentos de PAMP", "fundamental"),
        ("An\u00e1lisis fundamental de PAMP", "fundamental"),
        ("M\u00e9tricas fundamentales de PAMP", "fundamental"),
        ("Analiz\u00e1 GGAL", None),
        ("Analiz\u00e1 PAMP seg\u00fan Graham", None),
        ("Tendencia de ALUA", None),
        ("An\u00e1lisis t\u00e9cnico y fundamental de GGAL", None),
    ],
)
def test_explicit_dimension_only(message, expected):
    assert explicit_analysis_type(message) == expected


@pytest.mark.parametrize(
    "message,kind,not_requested",
    [
        ("Analiz\u00e1 t\u00e9cnicamente GGAL", "technical", "fundamental"),
        ("Analiz\u00e1 los fundamentos de PAMP", "fundamental", "technical"),
    ],
)
def test_first_http_failure_preserves_explicit_dimension(make_agent, message, kind, not_requested):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        provider = GeminiLLMProvider(
            http, "https://gemini.test/v1beta", "model", "test-key", max_retries=0
        )
        agent, repo = make_agent(provider=provider)
        result = agent.run(message)
    assert len(requests) == 1
    context = json.loads(requests[0]["contents"][0]["parts"][1]["text"])["agent_context"]
    assert context["intent"]["analysis_type"] == kind
    assert result.status == "ERROR"
    assert result.analysis_type == kind
    assert getattr(result, not_requested).status == "NOT_REQUESTED"
    state = repo.records[0][0]
    assert state.tool_calls == []
    assert all(e["state"]["analysis_type"] == kind for e in state.trace_events)
    transitions = [e.get("transition") for e in state.trace_events]
    assert transitions.count("RUNNING->ERROR") == 1
    assert "ERROR->ERROR" not in transitions


def test_error_then_persistence_failure_has_no_redundant_transition(make_agent):
    def fail(state):
        raise ExternalServiceError("unavailable")

    class BrokenRepository:
        def save(self, state, result):
            self.state = state
            raise OSError("failed")

    agent, _ = make_agent(provider=FakeLLMProvider(fail))
    repo = BrokenRepository()
    agent.repository = repo
    result = agent.run("GGAL")
    assert result.status == "ERROR"
    assert any(e.code == "PERSISTENCE_FAILURE" for e in result.errors)
    assert not any(e.get("transition") == "ERROR->ERROR" for e in repo.state.trace_events)
    assert any(e.get("error") == "PERSISTENCE_FAILURE" for e in repo.state.trace_events)


@pytest.mark.parametrize("status", [429, 500, 503])
def test_retry_delay_order_and_actual_sleep(monkeypatch, status):
    monkeypatch.setattr("merval_agent.adapters.llm.gemini.random", lambda: 0)
    timeline = []
    events = []
    monkeypatch.setattr(
        "merval_agent.adapters.llm.gemini.sleep", lambda delay: timeline.append(("sleep", delay))
    )

    def emit(name, **metadata):
        events.append({"event": name, **metadata})
        timeline.append((name, metadata.get("retry_delay_ms")))

    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(status))
    ) as http:
        provider = GeminiLLMProvider(
            http, "https://gemini.test/v1beta", "model", "test-key", max_retries=2
        )
        with pytest.raises(ExternalServiceError):
            provider.decide_validated(AgentState(user_request="GGAL"), [], lambda d: None, emit)
    assert timeline == [
        ("LLM_STARTED", None),
        ("LLM_FAILED", None),
        ("LLM_RETRY_DELAY", 500),
        ("sleep", 0.5),
        ("LLM_STARTED", None),
        ("LLM_FAILED", None),
        ("LLM_RETRY_DELAY", 1000),
        ("sleep", 1),
        ("LLM_STARTED", None),
        ("LLM_FAILED", None),
    ]
    delays = [e for e in events if e["event"] == "LLM_RETRY_DELAY"]
    assert [e["next_retry_number"] for e in delays] == [1, 2]
    assert all(e["provider"] == "gemini" for e in delays)


def test_domain_limitations_are_timeless(make_agent):
    agent, _ = make_agent()
    report = agent.run("Analiz\u00e1 GGAL")
    assert "Fase 1" not in report.model_dump_json()
    assert report.technical.status == "BULLISH"
    assert report.technical.assessment.status == "COMPLETE"
    assert report.fundamental.status == "INSUFFICIENT_DATA"
