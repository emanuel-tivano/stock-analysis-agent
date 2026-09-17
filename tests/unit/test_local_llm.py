import json
import runpy
from pathlib import Path

import httpx
import pytest

from merval_agent.config import Settings
from merval_agent.evaluation import evaluate, provider_environment

SCRIPT = Path(__file__).parents[2] / "scripts/run_real_llm.py"
SMOKE = runpy.run_path(str(SCRIPT))["smoke_provider"]
KEY = "private-dummy-key"
VALID = '{"action":"CLARIFY","reason":"private-response","confidence":1}'


def settings(port=11434, **kwargs):
    return Settings(
        _env_file=None,
        llm_provider="compatible",
        llm_base_url=f"http://127.0.0.1:{port}/v1",
        llm_model="test-instruct",
        llm_api_key=KEY,
        llm_timeout_seconds=120,
        **kwargs,
    )


@pytest.mark.parametrize("port", [11434, 1234])
@pytest.mark.parametrize("response_format", ["json_object", "none"])
def test_local_smoke_strict_retry_and_safe_output(port, response_format, capsys, caplog):
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == f"http://127.0.0.1:{port}/v1/chat/completions"
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert request.extensions["timeout"]["read"] == 120
        body = json.loads(request.content)
        assert body.get("response_format") == (
            {"type": "json_object"} if response_format == "json_object" else None
        )
        # No tolerant extraction from Markdown, even with response_format=none.
        content = f"```json\n{VALID}\n```" if len(requests) == 1 else VALID
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert SMOKE(settings(port, llm_response_format=response_format), client) == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert len(requests) == 2
    assert report["status"] == "OK"
    assert report["decision.action"] == "CLARIFY"
    assert report["usage"] is None
    assert set(report) == {"provider", "model", "status", "decision.action", "latency_ms", "usage"}
    assert KEY not in output + caplog.text
    assert "private-response" not in output
    assert "Necesito" not in output


def test_smoke_requires_opt_in(monkeypatch):
    monkeypatch.setenv("RUN_LLM_TESTS", "0")
    monkeypatch.setattr("sys.argv", [str(SCRIPT), "--provider-only"])
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: pytest.fail("No requests allowed"))
    with pytest.raises(SystemExit, match="RUN_LLM_TESTS"):
        runpy.run_path(str(SCRIPT), run_name="__main__")


@pytest.mark.parametrize("failure", ["timeout", "connection", 503])
def test_local_evaluator_availability_and_identity(failure, monkeypatch, tmp_path):
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout(KEY, request=request)
        if failure == "connection":
            raise httpx.ConnectError(KEY, request=request)
        return httpx.Response(failure)

    client_type = httpx.Client

    def offline_client(**kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return client_type(trust_env=False, **kwargs)

    monkeypatch.setattr(httpx, "Client", offline_client)
    case = {
        "id": "clarify",
        "input": "Necesito más información",
        "expected_tools": [],
        "forbidden_tools": [],
        "expected_status": ["CLARIFY"],
        "expected_asset": None,
    }
    report, path = evaluate(settings(), cases=[case], output_dir=tmp_path)
    assert report["provider"] == "compatible"
    assert report["model"] == "test-instruct"
    assert report["provider_environment"] == "local"
    assert report["response_format"] == "json_object"
    assert report["runs_per_case"] == 1
    assert report["prompt_version"] == "technical-v3"
    assert report["dataset_version"] == "technical-v3"
    assert report["llm_min_interval_seconds"] == 0
    metrics = report["metrics"]
    assert metrics["provider_error_cases"] == 1
    assert metrics["failed_cases"] == metrics["evaluated_cases"] == 0
    assert metrics["task_success_rate"] is None
    assert report["cases"][0]["result"] == "PROVIDER_ERROR"
    assert KEY not in path.read_text()
    with client_type(transport=httpx.MockTransport(handler)) as client:
        assert SMOKE(settings(), client) == 1


@pytest.mark.parametrize(
    "url,environment",
    [
        ("http://localhost:1234/v1", "local"),
        ("http://[::1]:1234/v1", "local"),
        ("https://user:secret@api.example/v1?key=secret", "remote"),
        ("http://192.168.1.10:1234/v1", "remote"),
    ],
)
def test_environment_is_loopback_only(url, environment):
    assert provider_environment(url) == environment
