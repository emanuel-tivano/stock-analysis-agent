import json

import httpx
import pytest

from merval_agent.adapters.llm.compatible import CompatibleLLMProvider
from merval_agent.config import Settings
from merval_agent.evaluation import evaluate
from merval_agent.evaluation_rate_limit import SequentialLLMRateLimiter


class Clock:
    def __init__(self):
        self.now = 0
        self.waits = []

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr("merval_agent.adapters.llm.gemini.random", lambda: 0)
    clock = Clock()
    monkeypatch.setattr("merval_agent.evaluation_rate_limit.monotonic", lambda: clock.now)
    monkeypatch.setattr("merval_agent.evaluation_rate_limit.sleep", clock.sleep)
    monkeypatch.setattr("merval_agent.adapters.llm.gemini.sleep", clock.sleep)
    monkeypatch.setattr("merval_agent.evaluation.sleep", clock.sleep)
    return clock


def test_consecutive_requests_and_elapsed_work(clock):
    limiter = SequentialLLMRateLimiter(15)
    limiter(None)
    assert clock.waits == []
    limiter(None)
    assert clock.now == 15
    clock.now += 6
    limiter(None)
    assert clock.waits == [15, 9]
    clock.now += 20
    limiter(None)
    assert clock.waits == [15, 9]


def test_zero_is_noop(monkeypatch):
    def fail(*args):
        pytest.fail("Disabled limiter must not read the clock or sleep")

    monkeypatch.setattr("merval_agent.evaluation_rate_limit.monotonic", fail)
    monkeypatch.setattr("merval_agent.evaluation_rate_limit.sleep", fail)
    limiter = SequentialLLMRateLimiter(0)
    limiter(None)
    limiter(None)


def test_multiple_steps_within_one_agent_run(clock, make_agent):
    starts = []

    def handler(request):
        starts.append(clock.now)
        decision = (
            {
                "action": "CALL_TOOL",
                "tool_name": "resolve_asset",
                "tool_args": {"query": "XXXX"},
                "reason": "Resolve",
                "confidence": 1,
                "intent": {"analysis_type": "technical", "methodology": []},
            }
            if len(starts) == 1
            else {"action": "CLARIFY", "reason": "Ticker?", "confidence": 1}
        )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(decision)}}]}
        )

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        event_hooks={"request": [SequentialLLMRateLimiter(15)]},
    ) as client:
        provider = CompatibleLLMProvider(client, "https://llm.test", "model", "offline-key")
        agent, repo = make_agent(provider=provider)
        assert agent.run("XXXX").status == "CLARIFY"
    # A resolved NOT_FOUND outcome is terminal; no second LLM decision is needed.
    assert starts == [0]
    assert len(repo.records[0][0].tool_calls) == 1


@pytest.mark.parametrize("interval", [-1, float("nan"), float("inf")])
def test_invalid_intervals(interval, tmp_path):
    with pytest.raises(ValueError):
        SequentialLLMRateLimiter(interval)
    with pytest.raises(ValueError):
        evaluate(
            Settings(_env_file=None),
            fake=True,
            output_dir=tmp_path,
            llm_min_interval_seconds=interval,
        )


@pytest.mark.parametrize("provider", ["gemini", "compatible"])
@pytest.mark.parametrize("failure", [503, 429, "invalid", "timeout"])
def test_eval_requests_retries_and_metrics(clock, monkeypatch, tmp_path, provider, failure):
    starts = []

    def handler(request):
        starts.append(clock.now)
        # Each run has one failed attempt followed by a valid decision.
        if len(starts) % 2:
            if isinstance(failure, int):
                return httpx.Response(failure)
            if failure == "timeout":
                raise httpx.ReadTimeout("offline", request=request)
            decision = {"action": "INVALID"}
        else:
            decision = {"action": "CLARIFY", "reason": "Ticker?", "confidence": 1}
        content = json.dumps(decision)
        payload = (
            {
                "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": content}]}}],
                "usageMetadata": {
                    "promptTokenCount": 20,
                    "candidatesTokenCount": 10,
                    "totalTokenCount": 30,
                },
            }
            if provider == "gemini"
            else {
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            }
        )
        return httpx.Response(200, json=payload)

    # Keep the evaluator's actual client, hooks and build_provider. Replace only
    # the network transport; fixture tool clients already have MockTransport.
    client_type = httpx.Client

    def offline_client(**kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return client_type(trust_env=False, **kwargs)

    monkeypatch.setattr(httpx, "Client", offline_client)
    monkeypatch.setattr("merval_agent.evaluation.perf_counter", lambda: 0)
    settings = Settings(
        _env_file=None,
        llm_provider=provider,
        llm_model="offline-model",
        llm_base_url="https://llm.test",
        llm_api_key="offline-key",
    )
    case = {
        "id": "clarify",
        "input": "Ticker?",
        "expected_tools": [],
        "forbidden_tools": [],
        "expected_status": ["CLARIFY"],
        "expected_asset": None,
    }

    def run(interval):
        starts.clear()
        clock.now = 0
        clock.waits.clear()
        return evaluate(
            settings,
            cases=[case, {**case, "id": "second"}],
            runs=2,
            output_dir=tmp_path,
            llm_min_interval_seconds=interval,
        )[0]

    baseline = run(0)
    paced = run(15)
    assert starts == list(range(0, 120, 15))
    assert paced["metrics"] == baseline["metrics"]
    assert paced["metrics"]["passed_cases"] == 4
    assert paced["llm_min_interval_seconds"] == 15
    assert paced["provider"] == provider
    assert paced["model"] == "offline-model"
    assert paced["rate_limit_strategy"] == "sequential_http_request_start_interval"
    assert baseline["rate_limit_strategy"] == "disabled"
    if provider == "gemini":
        assert clock.waits[:2] == [0.5, 14.5]


def test_fake_does_not_wait(clock, tmp_path):
    report, _ = evaluate(
        Settings(_env_file=None),
        fake=True,
        runs=2,
        output_dir=tmp_path,
        llm_min_interval_seconds=15,
        delay_seconds=5,
        provider_error_cooldown_seconds=30,
    )
    assert clock.waits == []
    assert report["llm_min_interval_seconds"] == 0
    assert report["rate_limit_strategy"] == "disabled"
