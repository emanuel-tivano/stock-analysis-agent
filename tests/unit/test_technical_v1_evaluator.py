import json
from pathlib import Path
from unittest.mock import patch

import pytest

from merval_agent.adapters.market_tracker import normalize_history
from merval_agent.domain.technical import calculate
from merval_agent.evaluation_technical_v1 import (
    AT,
    evaluate_case,
    fixture_payload,
    load_cases,
    score,
)


def test_scenarios_contain_actual_recent_crosses():
    h = normalize_history(fixture_payload({"pattern": "cross"}), "GGAL", "6M", "fixture://cross")
    before, after = calculate(h.bars[:-1]), calculate(h.bars)
    assert before.ema12 < before.ema26 and after.ema12 > after.ema26
    assert before.macd < before.macd_signal and after.macd > after.macd_signal


@pytest.mark.parametrize(
    "tamper,axis",
    [
        ("number", "numbers"),
        ("prose", "unsupported_claims"),
        ("classification", "classification"),
        ("trace", "tracing"),
    ],
)
def test_evaluator_detects_adulterated_outputs(make_agent, tamper, axis):
    case = load_cases()[0]
    agent, repo = make_agent(data=fixture_payload(case), clock=lambda: AT)
    result = agent.run(case["input"])
    state = repo.records[0][0]
    saved = (case["input"], result.executive_summary)
    if tamper == "number":
        result.technical.metrics.sma20 = 999999
    elif tamper == "prose":
        result.executive_summary += " RSI 999999; precio futuro 999999."
    elif tamper == "classification":
        result.technical.assessment.conclusion = "BEARISH"
    else:
        state.trace_events = []
    assert score(case, state, result, agent.tools, saved)["axes"][axis] == "FAIL"


def test_evaluation_does_not_replace_existing_results(tmp_path):
    path = tmp_path / "existing"
    path.mkdir()
    (path / "sentinel").write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError):
        evaluate_case(load_cases()[0], path)
    assert (path / "sentinel").read_text() == "preserve"


@pytest.mark.parametrize("kind", ["full", "technical"])
def test_explicit_full_report_guard_preserves_technical_evidence(make_agent, kind):
    from merval_agent.agents.report import build_report

    agent, repo = make_agent(data=fixture_payload({}), clock=lambda: AT)
    agent.run("Analiza técnicamente GGAL")
    state = repo.records[0][0]
    state.intent.analysis_type = kind
    state.user_request = "Análisis técnico y fundamental de GGAL"
    result = build_report(state, "Complete", "", 7)
    assert result.status == "ABSTAIN"
    assert result.technical.metrics and result.technical.assessment.status == "COMPLETE"
    if kind == "full":
        assert result.fundamental.status == "INSUFFICIENT_DATA"


def test_market_capture_requires_both_opt_ins(monkeypatch, tmp_path):
    import importlib.util

    path = Path(__file__).parents[2] / "scripts/capture_technical_v1.py"
    spec = importlib.util.spec_from_file_location("capture_v1", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.delenv("RUN_LIVE_TESTS", raising=False)
    with patch("sys.argv", [str(path), "--live"]), patch.object(module, "capture") as capture:
        with pytest.raises(SystemExit, match="2"):
            module.main()
        capture.assert_not_called()


def test_every_dataset_axis_is_exercised():
    cases = load_cases()
    assert len(cases) >= 25 and len({c["id"] for c in cases}) == len(cases)
    assert {c["status"] for c in cases} == {"ANSWER", "CLARIFY", "ABSTAIN", "ERROR"}
    assert {c.get("conclusion") for c in cases} >= {"BULLISH", "BEARISH", "NEUTRAL", "MIXED"}
    # Serializable expectations, never generated from current production classification.
    assert json.loads(json.dumps(cases)) == cases


@pytest.mark.parametrize(
    "tool,code",
    [
        ("calculate_technical_indicators", "CALCULATION_FAILED"),
        ("get_market_history", "EXTERNAL_SERVICE"),
    ],
)
def test_failed_refresh_never_retains_actionable_confidence(make_agent, tool, code):
    from merval_agent.agents.report import build_report
    from merval_agent.domain.models import ErrorInfo, ToolCall, ToolResult

    agent, repo = make_agent(data=fixture_payload({}), clock=lambda: AT)
    agent.run("Analiza técnicamente GGAL")
    state = repo.records[0][0]
    state.tool_calls.append(ToolCall(name=tool, arguments={"ticker": "GGAL"}))
    state.observations.append(
        ToolResult(
            tool_name=tool, success=False, error=ErrorInfo(code=code, message="fixture failure")
        )
    )
    result = build_report(state, "Complete", "", 7)
    assert result.status == "ERROR"
    assert result.technical.metrics  # Preserve valid earlier observations.
    assert result.technical.assessment.confidence == "UNAVAILABLE"
    assert result.technical.assessment.conclusion == "UNAVAILABLE"
