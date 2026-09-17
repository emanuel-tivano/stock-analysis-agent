import json
from pathlib import Path

import httpx
import pytest

from merval_agent.adapters.llm.compatible import CompatibleLLMProvider
from merval_agent.adapters.llm.fake import FakeLLMProvider
from merval_agent.agents.report import build_report
from merval_agent.agents.state import reduce_observation
from merval_agent.config import Settings
from merval_agent.domain.models import ToolCall
from merval_agent.evaluation import evaluate, load_cases, score_case


def decision(action="ABSTAIN", **kwargs):
    return {"action": action, "reason": "Test decision", "confidence": 1, **kwargs}


def call(name, **args):
    return decision("CALL_TOOL", tool_name=name, tool_args=args)


@pytest.fixture
def provider():
    clients = []

    def factory(outputs, retries=1):
        requests = []

        def handler(request):
            requests.append(json.loads(request.content))
            output = outputs[min(len(requests) - 1, len(outputs) - 1)]
            return httpx.Response(
                200, json={"choices": [{"message": {"content": json.dumps(output)}}]}
            )

        http = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(http)
        return CompatibleLLMProvider(
            http, "https://llm.test", "offline", "private", max_retries=retries
        ), requests

    yield factory
    for client in clients:
        client.close()


@pytest.mark.parametrize("terminal", ["CLARIFY", "ABSTAIN"])
def test_unknown_legitimate_terminal_without_unnecessary_lookup(make_agent, terminal):
    case = next(c for c in load_cases() if c["id"] == "unknown")
    agent, repo = make_agent(provider=FakeLLMProvider(lambda s: decision(terminal)))
    result = agent.run(case["input"])
    row = score_case(case, repo.records[0][0], result, 0)
    assert row["result"] == "PASS"
    assert row["tools_correct"] and row["abstention_correct"]
    assert repo.records[0][0].tool_calls == []


def test_unknown_lookup_path_still_passes_and_known_asset_not_waived(make_agent):
    case = next(c for c in load_cases() if c["id"] == "unknown")
    agent, repo = make_agent()
    result = agent.run(case["input"])
    assert score_case(case, repo.records[0][0], result, 0)["result"] == "PASS"
    assert [c.name for c in repo.records[0][0].tool_calls] == ["resolve_asset"]
    known = {**case, "expected_asset": "BMA"}
    assert score_case(known, repo.records[0][0], result, 0)["result"] == "FAIL"


@pytest.mark.parametrize(
    "status,attempts,error_kind,retryable",
    [(400, 1, "HTTP_400", False), (503, 2, "HTTP_503", True), (429, 2, "HTTP_429", True)],
)
def test_tool_failure_policy_and_correction(
    provider, make_agent, status, attempts, error_kind, retryable
):
    market = call("get_market_history", ticker="BMA", range="6M")
    real, requests = provider(
        [call("resolve_asset", query="BMA")] + [market] * (attempts + 1) + [decision()]
    )
    agent, repo = make_agent(provider=real, market_status=status)
    result = agent.run("Analisis tecnico BMA")
    state = repo.records[0][0]
    assert result.status == "ERROR"
    observations = [o for o in state.observations if o.tool_name == "get_market_history"]
    assert len(observations) == attempts
    assert observations[-1].error_kind == error_kind
    assert observations[-1].error.retryable == retryable
    assert observations[-1].attempts == attempts
    assert not observations[-1].can_retry
    assert observations[-1].retry_budget_exhausted == retryable
    assert len({o.operation_key for o in observations}) == 1
    feedback = json.loads(requests[-1]["messages"][-1]["content"])["previous_attempt_failed"]
    assert feedback["code"] == ("TOOL_RETRY_EXHAUSTED" if retryable else "TOOL_NOT_RETRYABLE")
    context = json.loads(requests[-2]["messages"][1]["content"])
    assert context["operation_observations"][-1]["attempts"] == attempts
    assert not context["operation_observations"][-1]["can_retry"]


def test_exhausted_tool_budget_cannot_be_bypassed_by_stubborn_model(provider, make_agent):
    market = call("get_market_history", ticker="BMA", range="6M")
    real, _ = provider([call("resolve_asset", query="BMA"), market, market, market])
    agent, repo = make_agent(provider=real, market_status=503)
    assert agent.run("Tecnico BMA").status == "ERROR"
    assert [c.name for c in repo.records[0][0].tool_calls].count("get_market_history") == 2


def test_missing_methodology_not_required_after_technical_data_failure(provider, make_agent):
    case = next(c for c in load_cases() if c["id"] == "market_failure")
    real, _ = provider(
        [
            call("resolve_asset", query="GGAL"),
            call("get_market_history", ticker="GGAL", range="6M"),
            decision(),
        ]
    )
    agent, repo = make_agent(provider=real, market_status=503)
    result = agent.run(case["input"])
    assert score_case(case, repo.records[0][0], result, 0)["result"] == "PASS"
    # An early abstention without the required data attempt is still a failure.
    agent, repo = make_agent(provider=FakeLLMProvider(lambda s: decision()))
    result = agent.run(case["input"])
    assert score_case(case, repo.records[0][0], result, 0)["result"] == "FAIL"


def test_known_observations_preserved_and_intent_change_repaired(provider, make_agent):
    search = call("search_methodology", query="trend", source="murphy")
    real, requests = provider(
        [
            call("resolve_asset", query="BMA"),
            call("get_market_history", ticker="BMA", range="6M"),
            call("calculate_technical_indicators", ticker="BMA"),
            {**search, "intent": {"analysis_type": "technical", "methodology": ["murphy"]}},
            search,
            decision("FINAL_ANSWER"),
        ]
    )
    agent, repo = make_agent(provider=real)
    result = agent.run("Analisis tecnico BMA")
    state = repo.records[0][0]
    assert result.status == "ANSWER"
    for request in requests[3:]:
        context = json.loads(request["messages"][1]["content"])
        assert context["history"]["ticker"] == "BMA"
        assert context["technical_metrics"]["sma20"] is not None
    feedback = json.loads(requests[4]["messages"][-1]["content"])
    assert feedback["previous_attempt_failed"]["code"] == "INTENT_CHANGE"
    assert feedback["intent_locked"]
    assert feedback["current_intent"]["methodology"] == []
    assert len(state.tool_calls) == 4
    assert len(state.observations) == 4
    assert not any(e.get("duplicate_tool_call") for e in state.trace_events)


def test_normalized_duplicate_rejected_without_execution_and_can_reuse(provider, make_agent):
    real, requests = provider(
        [
            call("resolve_asset", query="BMA"),
            call("get_market_history", ticker="BMA", range="6M"),
            call("get_market_history", ticker=" bma ", range="6M"),
            call("calculate_technical_indicators", ticker="BMA"),
            decision("FINAL_ANSWER"),
        ]
    )
    agent, repo = make_agent(provider=real)
    assert agent.run("Tecnico BMA").status == "ANSWER"
    state = repo.records[0][0]
    assert len(state.tool_calls) == 3
    assert state.technical_data and state.technical_metrics
    assert (
        json.loads(requests[3]["messages"][-1]["content"])["previous_attempt_failed"]["code"]
        == "duplicate_tool_call"
    )


def test_schema_diagnostics_safe_and_repair_bounded(provider, make_agent):
    bad = call("resolve_asset")
    bad["tool_args"] = {"secret-field": "private-value"}
    real, requests = provider([bad, decision("CLARIFY")])
    agent, repo = make_agent(provider=real)
    assert agent.run("Ambiguous").status == "CLARIFY"
    feedback = json.loads(requests[1]["messages"][-1]["content"])["previous_attempt_failed"]
    assert feedback["code"] == "SCHEMA_VALIDATION"
    assert any(i["field"] == ["query"] and i["type"] == "missing" for i in feedback["issues"])
    assert "private-value" not in json.dumps(repo.records[0][0].trace_events)
    assert "secret-field" not in json.dumps(feedback)
    real, requests = provider([bad], retries=2)
    agent, repo = make_agent(provider=real)
    assert agent.run("Ambiguous").status == "ERROR"
    assert len(requests) == 3 and not repo.records[0][0].tool_calls
    assert repo.records[0][0].errors[-1].code == "DECISION_BUDGET_EXHAUSTED"


@pytest.mark.parametrize(
    "bad,expected",
    [
        (decision("CLARIFY", tool_args={"query": "private"}), "TERMINAL_TOOL_FIELDS"),
        (decision("CLARIFY", reason="x" * 401), "DECISION_TEXT_BOUNDS"),
    ],
)
def test_cross_field_and_length_failures_have_actionable_feedback(
    provider, make_agent, bad, expected
):
    real, requests = provider([bad, decision("CLARIFY")])
    agent, _ = make_agent(provider=real)
    assert agent.run("Ambiguous").status == "CLARIFY"
    feedback = json.loads(requests[1]["messages"][-1]["content"])["previous_attempt_failed"]
    if expected == "TERMINAL_TOOL_FIELDS":
        assert feedback["issues"][0]["constraint"] == expected
    else:
        assert feedback["code"] == expected
        assert feedback["limits"]["reason"] == 400


def test_malformed_tool_response_is_preserved_as_failure_not_model_error(make_agent):
    agent, repo = make_agent()
    agent.tools.tools["get_market_history"].handler = lambda *a: {"bars": "invalid"}
    result = agent.run("Tecnico BMA")
    state = repo.records[0][0]
    failure = next(o for o in state.observations if o.tool_name == "get_market_history")
    assert not failure.success and failure.error_kind == "INVALID_RESPONSE"
    assert not failure.can_retry
    assert state.technical_data is None
    assert not any(e.code == "INVALID_DECISION" for e in result.errors)


def test_decision_budget_is_error_not_evidence_abstention(make_agent):
    agent, repo = make_agent(max_steps=1)
    assert agent.run("Tecnico BMA").status == "ERROR"
    assert repo.records[0][0].errors[-1].code == "MAX_STEPS_EXCEEDED"


@pytest.mark.parametrize(
    "explicit,model_methodology,expected",
    [
        (False, [], "ANSWER"),
        (False, ["murphy"], "ANSWER"),
        (True, [], "ABSTAIN"),
        (True, ["murphy"], "ABSTAIN"),
    ],
)
def test_explicit_methodology_requirement_is_not_inferred_from_model_plan(
    make_agent, explicit, model_methodology, expected
):
    agent, repo = make_agent()
    agent.run("Tecnico BMA")
    state = repo.records[0][0]
    state.intent.methodology = model_methodology
    state.user_request = "Tecnico BMA" + (" segun Murphy" if explicit else "")
    state.status = "ANSWER"
    result = build_report(state, "Calculated data", "No directional claim", 7)
    assert result.status == expected
    assert result.technical.status == ("INSUFFICIENT_DATA" if explicit else "BULLISH")
    assert result.fundamental.status == "NOT_REQUESTED"


def test_changed_history_allows_recalculation_without_false_duplicate_metric(make_agent):
    agent, repo = make_agent()
    result = agent.run("Tecnico GGAL")
    state = repo.records[0][0]
    state.technical_data = state.technical_data.model_copy(
        update={"bars": state.technical_data.bars[-30:]}
    )
    call = ToolCall(name="calculate_technical_indicators", arguments={"ticker": "GGAL"})
    observation = agent.tools.execute(call, state)
    assert observation.success
    state.tool_calls.append(call)
    reduce_observation(state, observation)
    row = score_case(load_cases()[0], state, result, 0)
    assert row["duplicate_tool_calls"] == 0
    with pytest.raises(ValueError, match="duplicate_tool_call"):
        agent.tools.prepare(call, state)


def test_cli_selected_cases_preserve_fixture_definitions(monkeypatch, tmp_path):
    import runpy
    import sys

    def capture(settings, **kwargs):
        assert kwargs["cases"] == [
            c for c in load_cases() if c["id"] in ("unknown", "known_observation")
        ]
        return {"metrics": {"failed_cases": 0}, "cases": []}, tmp_path / "report.json"

    monkeypatch.setattr("merval_agent.evaluation.evaluate", capture)
    monkeypatch.setattr(
        sys,
        "argv",
        ["eval_real_llm.py", "--fake", "--case-id", "unknown", "--case-id", "known_observation"],
    )
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(
            str(Path(__file__).parents[2] / "scripts/eval_real_llm.py"), run_name="__main__"
        )
    assert exc.value.code == 2


def test_cli_does_not_compare_subset_with_full_baseline(monkeypatch, tmp_path, capsys):
    import runpy
    import sys

    report = {
        "evaluator_version": "phase2-v3",
        "cases": [{"id": "unknown", "run": 1}],
        "metrics": {"failed_cases": 0, "provider_error_cases": 0, "not_evaluated_cases": 0},
    }
    baseline = {**report, "cases": [{"id": c["id"], "run": 1} for c in load_cases()]}
    (tmp_path / "fake_baseline.json").write_text(json.dumps(baseline))
    monkeypatch.setattr(
        "merval_agent.evaluation.evaluate", lambda *a, **kw: (report, tmp_path / "real.json")
    )
    monkeypatch.setenv("RUN_LLM_TESTS", "1")
    monkeypatch.setenv("LLM_PROVIDER", "compatible")
    monkeypatch.setenv("LLM_MODEL", "offline")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.test")
    monkeypatch.setenv("LLM_API_KEY", "private")
    monkeypatch.setattr(sys, "argv", ["eval_real_llm.py", "--case-id", "unknown"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(
            str(Path(__file__).parents[2] / "scripts/eval_real_llm.py"), run_name="__main__"
        )
    assert exc.value.code == 0
    assert "not comparable" in capsys.readouterr().out


SCENARIOS = json.loads(
    (Path(__file__).parents[1] / "fixtures/phase2_successful_actions.json").read_text()
)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s["id"])
def test_original_14_successful_semantic_traces_still_pass(
    scenario, provider, monkeypatch, tmp_path
):
    case = next(c for c in load_cases() if c["id"] == scenario["id"])
    outputs = json.loads(json.dumps(scenario["decisions"]))
    # Historical telemetry omitted intent payloads. Reconstruct the explicit
    # fixture intent; this replay preserves actions, not the raw model response.
    outputs[0]["intent"] = {
        "analysis_type": case.get("expected_analysis_type", "full"),
        "methodology": [
            source for source in ("murphy", "graham") if source in case["input"].lower()
        ],
    }
    for d in outputs:
        if "query" in d.get("tool_args", {}):
            d["tool_args"]["query"] = case["input"]
    real, _ = provider(outputs)
    monkeypatch.setattr("merval_agent.evaluation.build_provider", lambda *args: real)
    report, _ = evaluate(
        Settings(_env_file=None, llm_provider="compatible"), cases=[case], output_dir=tmp_path
    )
    assert report["cases"][0]["result"] == "PASS"
