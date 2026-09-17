import json
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from merval_agent.adapters.llm.gemini import GeminiLLMProvider
from merval_agent.api.app import create_app
from merval_agent.bootstrap import build_provider
from merval_agent.config import Settings
from merval_agent.domain.errors import DecisionBudgetExhausted, ExternalServiceError
from merval_agent.domain.models import AgentState
from merval_agent.domain.technical import calculate
from merval_agent.memory.sqlite import SQLiteRepository

KEY = "NEVER-PRINT-THIS-KEY"


def envelope(action="CLARIFY", **kwargs):
    decision = {"action": action, "reason": "operation", "confidence": 1, **kwargs}
    return {
        "modelVersion": "tested-version",
        "candidates": [
            {"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(decision)}]}}
        ],
    }


@pytest.mark.parametrize(
    "header,delay",
    [("3", 3), ("Wed, 16 Sep 2026 22:00:04 GMT", 4), ("invalid", 0.75), ("NaN", 0.75)],
)
def test_retry_after_and_injected_jitter(header, delay):
    calls = []
    sleeps = []
    events = []

    def handler(request):
        calls.append(request)
        return (
            httpx.Response(429, headers={"Retry-After": header})
            if len(calls) == 1
            else httpx.Response(200, json=envelope())
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        provider = GeminiLLMProvider(
            http,
            "https://gemini.test",
            "primary",
            KEY,
            sleeper=sleeps.append,
            random_source=lambda: 0.5,
            clock=lambda: datetime(2026, 9, 16, 22, tzinfo=UTC),
        )
        result = provider.decide_validated(
            AgentState(user_request="GGAL"),
            [],
            lambda d: None,
            lambda name, **fields: events.append({"event": name, **fields}),
        )
    assert result.action == "CLARIFY" and sleeps == [delay] and len(calls) == 2
    assert events[1]["error_class"] == "RATE_LIMITED"
    assert events[-1]["modelVersion"] == "tested-version"
    assert KEY not in json.dumps(events)


def test_backoff_max_attempts_and_no_early_retry():
    sleeps = []
    events = []
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))) as http:
        provider = GeminiLLMProvider(
            http,
            "https://gemini.test",
            "primary",
            KEY,
            max_retries=2,
            sleeper=sleeps.append,
            random_source=lambda: 0.5,
        )
        with pytest.raises(ExternalServiceError) as error:
            provider.decide_validated(
                AgentState(user_request="GGAL"),
                [],
                lambda d: None,
                lambda name, **fields: events.append({"event": name, **fields}),
            )
        assert error.value.classification == "RATE_LIMITED"
    assert sleeps == [0.75, 1.5]
    assert sum(e["event"] == "LLM_FAILED" for e in events) == 3
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={"Retry-After": "120"}))
    ) as http:
        provider = GeminiLLMProvider(
            http,
            "https://gemini.test",
            "primary",
            KEY,
            sleeper=lambda n: pytest.fail("Must defer, not retry early"),
        )
        with pytest.raises(ExternalServiceError):
            provider.decide(AgentState(user_request="GGAL"), [])


def test_structured_daily_quota_is_not_model_validation():
    body = {
        "error": {
            "status": "RESOURCE_EXHAUSTED",
            "message": KEY,
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}],
                }
            ],
        }
    }
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(429, json=body))
    ) as http:
        p = GeminiLLMProvider(
            http,
            "https://gemini.test",
            "primary",
            KEY,
            sleeper=lambda n: pytest.fail("Daily quota is not retried"),
        )
        with pytest.raises(ExternalServiceError) as exc:
            p.decide(AgentState(user_request="GGAL"), [])
        assert exc.value.classification == "QUOTA_EXHAUSTED"
        assert not isinstance(exc.value, DecisionBudgetExhausted)


@pytest.mark.parametrize("enabled", [False, True])
def test_model_fallback_explicit_and_allowlisted(enabled):
    seen = []
    events = []

    def handler(r):
        seen.append(r.url.path)
        return (
            httpx.Response(429)
            if "primary:" in r.url.path
            else httpx.Response(200, json=envelope())
        )

    settings = Settings(
        _env_file=None,
        llm_provider="gemini",
        llm_base_url="https://gemini.test",
        llm_model="primary",
        llm_api_key=KEY,
        llm_max_retries=0,
        llm_fallback_enabled=enabled,
        llm_fallback_model="backup",
        llm_allowed_fallback_models=["backup"],
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        p = build_provider(settings, http)

        def fn():
            return p.decide_validated(
                AgentState(user_request="GGAL"),
                [],
                lambda d: None,
                lambda name, **fields: events.append({"event": name, **fields}),
            )

        if enabled:
            assert fn().action == "CLARIFY"
            assert events[-1]["model"] == "backup"
            assert any(e["event"] == "LLM_MODEL_FALLBACK" for e in events)
        else:
            with pytest.raises(ExternalServiceError):
                fn()
    assert len(seen) == (2 if enabled else 1)
    assert KEY not in json.dumps(events)


def test_unlisted_fallback_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_fallback_enabled=True, llm_fallback_model="backup")


def test_backup_model_is_recorded_in_api_and_does_not_retry_primary_next_step(make_agent):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if "primary:" in request.url.path:
            return httpx.Response(503)
        return httpx.Response(200, json=envelope())

    settings = Settings(
        _env_file=None,
        llm_provider="gemini",
        llm_base_url="https://gemini.test",
        llm_model="primary",
        llm_api_key=KEY,
        llm_max_retries=0,
        llm_fallback_enabled=True,
        llm_fallback_model="backup",
        llm_allowed_fallback_models=["backup"],
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        provider = build_provider(settings, http)
        agent, memory = make_agent(provider=provider)
        result = agent.run("Analiza técnicamente GGAL")
        assert result.generation.requested_model == "primary"
        assert result.generation.model == "backup"
        assert result.generation.model_version == "tested-version"
        assert result.generation.model_fallback_used
        assert result.generation.warnings
        state = memory.records[-1][0]
        provider.decide_validated(state, [], lambda d: None, lambda *a, **k: None)
    assert sum("primary:" in p for p in paths) == 1
    assert sum("backup:" in p for p in paths) == 2


def test_invalid_decision_does_not_switch_models():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json=envelope("INVALID"))

    settings = Settings(
        _env_file=None,
        llm_provider="gemini",
        llm_base_url="https://gemini.test",
        llm_model="primary",
        llm_api_key=KEY,
        llm_max_retries=0,
        llm_fallback_enabled=True,
        llm_fallback_model="backup",
        llm_allowed_fallback_models=["backup"],
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(DecisionBudgetExhausted):
            build_provider(settings, http).decide(AgentState(user_request="GGAL"), [])
    assert len(paths) == 1 and "primary:" in paths[0]


def test_deterministic_fallback_can_be_disabled(make_agent):
    from merval_agent.domain.models import AgentDecision

    class FailAfterMetrics:
        def decide(self, state, tools):
            if not state.resolved_asset:
                return AgentDecision(
                    action="CALL_TOOL",
                    tool_name="resolve_asset",
                    tool_args={"query": "GGAL"},
                    reason="resolve",
                    confidence=1,
                )
            if not state.technical_data:
                return AgentDecision(
                    action="CALL_TOOL",
                    tool_name="get_market_history",
                    tool_args={"ticker": "GGAL", "range": "6M"},
                    reason="history",
                    confidence=1,
                )
            if not state.technical_metrics:
                return AgentDecision(
                    action="CALL_TOOL",
                    tool_name="calculate_technical_indicators",
                    tool_args={"ticker": "GGAL"},
                    reason="calculate",
                    confidence=1,
                )
            raise ExternalServiceError("limited", retryable=True, classification="RATE_LIMITED")

    agent, _ = make_agent(provider=FailAfterMetrics())
    agent.deterministic_fallback = False
    result = agent.run("Analiza técnicamente GGAL")
    assert result.status == "ERROR" and result.technical.metrics is not None


def test_calculation_error_is_distinct_from_market_failure(make_agent):
    agent, _ = make_agent()

    def fail(*args):
        raise OverflowError("calculation")

    agent.tools.tools["calculate_technical_indicators"].handler = fail
    result = agent.run("Analiza técnicamente GGAL")
    assert result.status == "ERROR"
    assert result.errors[-1].code == "CALCULATION_FAILED"
    assert result.technical.status == "INVALID_DATA"


@pytest.mark.parametrize(
    "failure,expected,mode",
    [
        (429, "ANSWER", "DETERMINISTIC_FALLBACK"),
        (503, "ANSWER", "DETERMINISTIC_FALLBACK"),
        ("invalid", "ERROR", "FAILED"),
    ],
)
def test_failure_after_calculation_preserves_verified_result(
    make_agent, tmp_path, failure, expected, mode
):
    steps = [
        envelope(
            "CALL_TOOL",
            tool_name="resolve_asset",
            tool_args={"query": "GGAL"},
            intent={"analysis_type": "technical"},
        ),
        envelope(
            "CALL_TOOL", tool_name="get_market_history", tool_args={"ticker": "GGAL", "range": "6M"}
        ),
        envelope(
            "CALL_TOOL", tool_name="calculate_technical_indicators", tool_args={"ticker": "GGAL"}
        ),
    ]

    def handler(r):
        if steps:
            return httpx.Response(200, json=steps.pop(0))
        return (
            httpx.Response(200, json=envelope("NOT_AN_ACTION"))
            if failure == "invalid"
            else httpx.Response(failure)
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        provider = GeminiLLMProvider(
            http,
            "https://gemini.test",
            "primary",
            KEY,
            max_retries=1,
            sleeper=lambda _: None,
            random_source=lambda: 0,
        )
        agent, memory = make_agent(provider=provider)
        sqlite = SQLiteRepository(str(tmp_path / "trace.sqlite3"))

        class Both:
            def save(self, state, result):
                memory.save(state, result)
                sqlite.save(state, result)

        agent.repository = Both()
        with TestClient(create_app(agent=agent, settings=Settings(_env_file=None))) as client:
            response = client.post("/agent/run", json={"message": "Analiza técnicamente GGAL"})
        data = response.json()
    assert data["status"] == expected and data["generation"]["mode"] == mode
    assert data["generation"]["model"] == "primary" and data["generation"]["attempts"] == 5
    assert data["generation"]["llm_status"] == (
        "INVALID_OUTPUT"
        if failure == "invalid"
        else "RATE_LIMITED"
        if failure == 429
        else "UNAVAILABLE"
    )
    state, result = memory.records[-1]
    assert result.technical.metrics == calculate(state.technical_data.bars)
    trace = sqlite.get_trace(result.trace_id)
    assert trace["events"][-1]["generation"]["mode"] == mode
    assert KEY not in json.dumps(trace) and KEY not in response.text
    assert result.errors  # Failure remains visible even with an ANSWER.
