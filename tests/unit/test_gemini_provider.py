import json
import logging

import httpx
import pytest

from merval_agent.adapters.llm.context import get_system_instructions
from merval_agent.adapters.llm.gemini import GeminiLLMProvider
from merval_agent.domain.models import AgentState

KEY = "private-test-key"
DECISION = {"action": "CLARIFY", "reason": "Confirm ticker", "confidence": 1}


def envelope(text=None, **extra):
    return {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {
                            "thought": True,
                            "text": "private-thinking",
                            "thoughtSignature": "private-signature",
                        },
                        {
                            "text": json.dumps(DECISION) if text is None else text,
                            "thoughtSignature": "private-signature",
                        },
                    ]
                },
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 20,
            "candidatesTokenCount": 10,
            "totalTokenCount": 35,
            "thoughtsTokenCount": 5,
        },
        "modelVersion": "gemini-test-001",
        "responseId": "response-001",
        **extra,
    }


@pytest.fixture
def make_gemini(monkeypatch):
    monkeypatch.setattr("merval_agent.adapters.llm.gemini.sleep", lambda seconds: None)
    clients = []

    def factory(outputs):
        requests = []

        def handler(request):
            requests.append(request)
            output = outputs[min(len(requests) - 1, len(outputs) - 1)]
            if isinstance(output, int):
                return httpx.Response(output, json={"error": {"message": KEY, "status": KEY}})
            if isinstance(output, Exception):
                raise output
            return httpx.Response(200, json=output)

        http = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(http)
        return GeminiLLMProvider(http, "https://gemini.test/v1beta", "gemini-test", KEY), requests

    yield factory
    for client in clients:
        client.close()


def test_native_request_response_usage_privacy(make_gemini, make_agent, caplog):
    real, requests = make_gemini([envelope()])
    real.response_format = "json_schema"
    agent, repo = make_agent(provider=real)
    with caplog.at_level(logging.INFO):
        assert agent.run("private-user-request").status == "CLARIFY"
    request = requests[0]
    assert request.url.path == "/v1beta/models/gemini-test:generateContent"
    assert request.headers["x-goog-api-key"] == KEY
    assert request.headers["content-type"] == "application/json"
    assert "authorization" not in request.headers
    assert not request.url.query
    body = json.loads(request.content)
    assert body["systemInstruction"]["parts"][0]["text"].startswith(
        get_system_instructions("technical-v3")
    )
    parts = body["contents"][0]["parts"]
    assert json.loads(parts[0]["text"]) == {"user_request": "private-user-request"}
    assert "agent_context" in json.loads(parts[1]["text"])
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["responseJsonSchema"]["title"] == "AgentDecision"
    assert "tools" not in body
    events = repo.records[0][0].trace_events
    success = next(e for e in events if e["event"] == "LLM_SUCCEEDED")
    assert success["provider"] == "gemini"
    assert success["modelVersion"] == "gemini-test-001"
    assert success["responseId"] == "response-001"
    assert success["usage"] == {
        "prompt_tokens": 20,
        "completion_tokens": 10,
        "total_tokens": 35,
        "reasoning_tokens": 5,
    }
    serialized = json.dumps(events) + caplog.text
    assert all(
        x not in serialized
        for x in (
            KEY,
            "x-goog-api-key",
            "thoughtSignature",
            "private-signature",
            "private-thinking",
            "private-user-request",
        )
    )


@pytest.mark.parametrize(
    "bad,event,code",
    [
        (envelope("not json"), "DECISION_VALIDATION_FAILED", "INVALID_DECISION"),
        (envelope("{}"), "DECISION_VALIDATION_FAILED", "INVALID_DECISION"),
        (
            envelope('{"action":"INVALID","reason":"x","confidence":1}'),
            "DECISION_VALIDATION_FAILED",
            "INVALID_DECISION",
        ),
        (503, "LLM_FAILED", "UNAVAILABLE"),
        (429, "LLM_FAILED", "RESOURCE_EXHAUSTED"),
        (httpx.ReadTimeout("private-timeout"), "LLM_FAILED", "TIMEOUT"),
        ({}, "LLM_FAILED", "NO_CANDIDATES"),
        ({"candidates": []}, "LLM_FAILED", "NO_CANDIDATES"),
        (
            envelope(
                candidates=[
                    {"finishReason": "STOP", "content": {"parts": [{"thoughtSignature": "secret"}]}}
                ]
            ),
            "LLM_FAILED",
            "NO_TEXT",
        ),
        (
            envelope(candidates=[{"finishReason": "MAX_TOKENS"}]),
            "LLM_FAILED",
            "UNUSABLE_FINISH_REASON",
        ),
        (envelope("   "), "LLM_FAILED", "NO_TEXT"),
    ],
)
def test_retryable_failures(make_gemini, make_agent, bad, event, code):
    real, requests = make_gemini([bad, envelope()])
    agent, repo = make_agent(provider=real)
    assert agent.run("GGAL").status == "CLARIFY"
    assert len(requests) == 2
    failure = next(e for e in repo.records[0][0].trace_events if e["event"] == event)
    assert failure["retryable"] is True
    assert failure["provider_error_code"] == code
    if isinstance(bad, int):
        assert failure["http_status"] == bad


@pytest.mark.parametrize(
    "bad", [400, 401, 403, 404, envelope(candidates=[{"finishReason": "SAFETY"}])]
)
def test_permanent_failure_no_retry(make_gemini, make_agent, bad):
    real, requests = make_gemini([bad])
    agent, repo = make_agent(provider=real)
    assert agent.run("GGAL").status == "ERROR"
    assert len(requests) == 1
    failure = next(e for e in repo.records[0][0].trace_events if e["event"] == "LLM_FAILED")
    assert failure["retryable"] is False
    assert KEY not in json.dumps(repo.records[0][0].trace_events)


def test_unknown_tool_business_validation_and_retry(make_gemini, make_agent):
    bad = {**DECISION, "action": "CALL_TOOL", "tool_name": "unknown", "tool_args": {}}
    real, requests = make_gemini([envelope(json.dumps(bad)), envelope()])
    agent, repo = make_agent(provider=real)
    assert agent.run("GGAL").status == "CLARIFY"
    assert len(requests) == 2
    assert repo.records[0][0].tool_calls == []


def test_retry_exhaustion(make_gemini, make_agent):
    real, requests = make_gemini([503])
    real.max_retries = 2
    agent, _ = make_agent(provider=real)
    assert agent.run("GGAL").status == "ERROR"
    assert len(requests) == 3


def test_split_text_and_missing_usage(make_gemini):
    payload = envelope(usageMetadata={})
    raw = json.dumps(DECISION)
    payload["candidates"][0]["content"]["parts"] = [{"text": raw[:20]}, {"text": raw[20:]}]
    real, _ = make_gemini([payload])
    assert real.decide(AgentState(user_request="Ticker?"), []).action == "CLARIFY"


def test_gemini_factory_and_shared_evaluator(monkeypatch, tmp_path):
    from merval_agent.config import Settings
    from merval_agent.evaluation import evaluate

    requests = []
    original = httpx.Client

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=envelope())

    def client(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    settings = Settings(
        _env_file=None,
        llm_provider="gemini",
        llm_base_url="https://gemini.test/v1beta",
        llm_model="gemini-test",
        llm_api_key=KEY,
        llm_input_price_per_1m=1,
        llm_output_price_per_1m=1,
    )
    case = {
        "id": "ambiguous",
        "input": "Ticker?",
        "expected_status": ["CLARIFY"],
        "expected_tools": [],
        "forbidden_tools": [],
        "expected_asset": None,
    }
    report, _ = evaluate(settings, cases=[case], output_dir=tmp_path)
    assert report["provider"] == "gemini"
    assert report["dataset_version"] == "technical-v3"
    assert report["metrics"]["task_success_rate"] == 1
    assert report["metrics"]["reasoning_tokens"] == 5
    assert report["metrics"]["cost"] is None
    assert len(requests) == 1
    assert requests[0].url.path.endswith(":generateContent")


def test_gemini_backoff_is_bounded(monkeypatch):
    monkeypatch.setattr("merval_agent.adapters.llm.gemini.random", lambda: 0)
    delays = []
    monkeypatch.setattr("merval_agent.adapters.llm.gemini.sleep", delays.append)
    with httpx.Client() as http:
        real = GeminiLLMProvider(http, "https://gemini.test/v1beta", "model", KEY)
        for retry in (0, 1, 2, 3):
            real.backoff(retry)
    assert delays == [0.5, 1, 2, 2]
