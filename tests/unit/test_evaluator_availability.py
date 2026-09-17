import copy
import json

import httpx
import pytest

from merval_agent.adapters.llm.gemini import GeminiLLMProvider
from merval_agent.config import Settings
from merval_agent.evaluation import aggregate, evaluate, load_cases, score_case


@pytest.fixture
def mock_provider(monkeypatch):
    clients = []
    monkeypatch.setattr("merval_agent.adapters.llm.gemini.sleep", lambda _: None)

    def factory(responses):
        requests = []

        def handler(request):
            item = responses[min(len(requests), len(responses) - 1)]
            requests.append(request)
            if isinstance(item, Exception):
                raise item
            if isinstance(item, int):
                return httpx.Response(item, json={"error": {"message": "secret-not-for-report"}})
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(item)}]}}
                    ]
                },
            )

        http = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(http)
        provider = GeminiLLMProvider(
            http, "https://gemini.test/v1beta", "model", "private-key", max_retries=2
        )
        monkeypatch.setattr("merval_agent.evaluation.build_provider", lambda *args: provider)
        return provider, requests

    yield factory
    for client in clients:
        client.close()


@pytest.fixture
def settings():
    return Settings(_env_file=None, llm_provider="gemini")


def clarification():
    return {"action": "CLARIFY", "reason": "Confirm ticker", "confidence": 1}


def simple_case():
    return {
        "id": "clarify",
        "input": "Ticker?",
        "expected_tools": [],
        "forbidden_tools": [],
        "expected_status": ["CLARIFY"],
        "expected_asset": None,
    }


@pytest.mark.parametrize(
    "responses,statuses,codes",
    [
        ([429], [429] * 3, ["RESOURCE_EXHAUSTED"] * 3),
        ([503], [503] * 3, ["UNAVAILABLE"] * 3),
        (
            [429, 503, 429],
            [429, 503, 429],
            ["RESOURCE_EXHAUSTED", "UNAVAILABLE", "RESOURCE_EXHAUSTED"],
        ),
        ([httpx.ReadTimeout("private-timeout")], [None] * 3, ["TIMEOUT"] * 3),
    ],
)
def test_exhausted_provider_is_not_functional_failure(
    mock_provider, settings, tmp_path, responses, statuses, codes
):
    _, requests = mock_provider(responses)
    report, path = evaluate(settings, cases=[load_cases()[0]], output_dir=tmp_path)
    assert len(requests) == 3
    row = report["cases"][0]
    assert row["result"] == "PROVIDER_ERROR"
    assert row["provider_error"] == {"http_statuses": statuses, "codes": codes}
    assert row["task_success"] is None and row["tools_correct"] is None
    assert row["forbidden_tool_violations"] == 0
    metrics = report["metrics"]
    assert metrics["total_cases"] == metrics["provider_error_cases"] == 1
    assert metrics["evaluated_cases"] == metrics["passed_cases"] == metrics["failed_cases"] == 0
    assert metrics["task_success_rate"] is None
    assert metrics["tool_selection_accuracy"] is None
    assert metrics["invalid_decision_rate"] is None
    assert metrics["provider_error_rate"] == 1
    assert metrics["provider_errors"] == 3
    assert all(
        secret not in path.read_text(encoding="utf-8")
        for secret in ("private-key", "private-timeout", "secret-not-for-report")
    )


def test_success_denominator_excludes_provider_and_not_evaluated(make_agent):
    agent, repo = make_agent()
    result = agent.run(load_cases()[0]["input"])
    state = repo.records[0][0]
    passed = score_case(load_cases()[0], state, result, 10)
    failed = copy.deepcopy(passed)
    failed.update(id="fail", result="FAIL", task_success=False, tools_correct=False)
    provider_error = copy.deepcopy(passed)
    provider_error.update(
        id="provider",
        result="PROVIDER_ERROR",
        task_success=None,
        tools_correct=None,
        invalid_decisions=2,
        decision_attempts=3,
    )
    unavailable = copy.deepcopy(provider_error)
    unavailable.update(id="unavailable", result="NOT_EVALUATED")
    metrics = aggregate([passed, failed, provider_error, unavailable], Settings(_env_file=None))
    assert metrics["total_cases"] == 4
    assert metrics["evaluated_cases"] == 2
    assert (
        metrics["passed_cases"]
        == metrics["failed_cases"]
        == metrics["provider_error_cases"]
        == metrics["not_evaluated_cases"]
        == 1
    )
    assert metrics["task_success_rate"] == metrics["tool_selection_accuracy"] == 0.5
    assert metrics["provider_error_rate"] == 0.25
    assert metrics["invalid_decision_rate"] == 0
    assert metrics["observed_invalid_decisions"] == 4


def test_invalid_decision_exhaustion_remains_model_failure(mock_provider, settings, tmp_path):
    mock_provider([{"action": "INVALID"}])
    report, _ = evaluate(settings, cases=[simple_case()], output_dir=tmp_path)
    assert report["cases"][0]["result"] == "FAIL"
    assert report["metrics"]["failed_cases"] == 1
    assert report["metrics"]["provider_error_cases"] == 0
    assert report["metrics"]["invalid_decision_rate"] == 1


def test_recovered_provider_failure_still_evaluated(mock_provider, settings, tmp_path):
    mock_provider([503, clarification()])
    report, _ = evaluate(settings, cases=[simple_case()], output_dir=tmp_path)
    assert report["cases"][0]["result"] == "PASS"
    assert report["metrics"]["provider_errors"] == 1
    assert report["metrics"]["provider_error_cases"] == 0
    assert report["metrics"]["task_success_rate"] == 1


def test_persistence_failure_is_not_evaluated(mock_provider, settings, tmp_path, monkeypatch):
    mock_provider([clarification()])

    def fail(*args):
        raise OSError("private-storage-error")

    monkeypatch.setattr("merval_agent.evaluation.SQLiteRepository.save", fail)
    report, _ = evaluate(settings, cases=[simple_case()], output_dir=tmp_path)
    assert report["cases"][0]["result"] == "NOT_EVALUATED"
    assert report["metrics"]["failed_cases"] == 0
    assert report["metrics"]["not_evaluated_cases"] == 1


def test_delays_between_cases_and_repetitions_only(mock_provider, settings, tmp_path, monkeypatch):
    _, requests = mock_provider([clarification()])
    waits = []
    monkeypatch.setattr(
        "merval_agent.evaluation.sleep", lambda seconds: waits.append((seconds, len(requests)))
    )
    cases = [simple_case(), {**simple_case(), "id": "second"}]
    report, _ = evaluate(settings, cases=cases, runs=2, output_dir=tmp_path, delay_seconds=5)
    assert waits == [(5, 1), (5, 2), (5, 3)]
    assert [r["delay_before_run_seconds"] for r in report["cases"]] == [0, 5, 5, 5]
    assert report["delay_seconds"] == 5
    assert report["metrics"]["total_cases"] == 4


@pytest.mark.parametrize(
    "responses,delay",
    [
        ([429, 429, 429, clarification()], 30),
        ([429, 503, 429, clarification()], 30),
        ([503, 503, 503, clarification()], 5),
        ([429, 503, 503, clarification()], 5),
        ([429, clarification(), clarification()], 5),
    ],
)
def test_cooldown_only_after_terminal_rate_limit(
    mock_provider, settings, tmp_path, monkeypatch, responses, delay
):
    _, requests = mock_provider(responses)
    waits = []
    monkeypatch.setattr("merval_agent.evaluation.sleep", waits.append)
    report, _ = evaluate(
        settings,
        cases=[simple_case()],
        runs=2,
        output_dir=tmp_path,
        delay_seconds=5,
        provider_error_cooldown_seconds=30,
    )
    assert waits == [delay]
    assert len(requests) == len(responses)  # No automatic whole-case retry.
    assert report["provider_error_cooldown_seconds"] == 30
    assert report["cases"][1]["delay_before_run_seconds"] == delay


def test_fake_never_sleeps(settings, tmp_path, monkeypatch):
    def fail(*args):
        pytest.fail("Fake must not throttle or construct a real provider")

    monkeypatch.setattr("merval_agent.evaluation.sleep", fail)
    monkeypatch.setattr("merval_agent.evaluation.build_provider", fail)
    report, _ = evaluate(
        settings,
        fake=True,
        cases=[load_cases()[0]],
        runs=3,
        output_dir=tmp_path,
        delay_seconds=5,
        provider_error_cooldown_seconds=30,
    )
    assert report["metrics"]["task_success_rate"] == 1
    assert report["delay_seconds"] == report["provider_error_cooldown_seconds"] == 0
    assert all(r["delay_before_run_seconds"] == 0 for r in report["cases"])


@pytest.mark.parametrize("delay", [-1, float("nan"), float("inf")])
def test_invalid_delays_rejected(settings, tmp_path, delay):
    with pytest.raises(ValueError, match="Delays"):
        evaluate(settings, cases=[], output_dir=tmp_path, delay_seconds=delay)


def test_tool_error_is_not_provider_error(make_agent):
    case = next(c for c in load_cases() if c["id"] == "market_failure")
    agent, repo = make_agent(market_status=503)
    result = agent.run(case["input"])
    row = score_case(case, repo.records[0][0], result, 10)
    assert row["result"] == "PASS"
    assert row["provider_error"] is None
    assert row["provider_errors"] == 0


def test_recovered_transport_error_not_in_invalid_decision_denominator(
    mock_provider, settings, tmp_path
):
    mock_provider([503, {"action": "INVALID"}, clarification()])
    report, _ = evaluate(settings, cases=[simple_case()], output_dir=tmp_path)
    assert report["cases"][0]["result"] == "PASS"
    assert report["metrics"]["invalid_decision_rate"] == 0.5
    assert report["metrics"]["provider_errors"] == 1


@pytest.mark.parametrize(
    "result,expected", [("PASS", 0), ("FAIL", 1), ("PROVIDER_ERROR", 2), ("NOT_EVALUATED", 2)]
)
def test_cli_exit_codes_distinguish_incomplete_evaluation(result, expected):
    import runpy
    from pathlib import Path

    exit_code = runpy.run_path(str(Path(__file__).parents[2] / "scripts/eval_real_llm.py"))[
        "exit_code"
    ]
    report = {
        "cases": [{"result": result}],
        "metrics": {
            "failed_cases": int(result == "FAIL"),
            "provider_error_cases": int(result == "PROVIDER_ERROR"),
            "not_evaluated_cases": int(result == "NOT_EVALUATED"),
        },
    }
    assert exit_code(report) == expected
