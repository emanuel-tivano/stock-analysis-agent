import copy

import pytest

from merval_agent.config import Settings
from merval_agent.evaluation import aggregate, evaluate, load_cases, score_case


def test_semantic_scoring_counts_rejected_calls(make_agent):
    agent, repo = make_agent()
    result = agent.run("Analiz\u00e1 t\u00e9cnicamente GGAL")
    state = repo.records[0][0]
    case = load_cases()[0]
    row = score_case(case, state, result, 10)
    assert row["task_success"]
    wrong_branch = result.model_copy(update={"analysis_type": "full"})
    assert not score_case(case, state, wrong_branch, 10)["task_success"]
    state.trace_events.append(
        {
            "event": "DECISION_VALIDATION_FAILED",
            "tool_name": "search_methodology",
            "source": "graham",
        }
    )
    row = score_case(case, state, result, 10)
    assert not row["task_success"]
    assert row["forbidden_tool_violations"] == 1
    assert row["invalid_decisions"] == 1


def test_cost_and_partial_usage(make_agent):
    agent, repo = make_agent()
    result = agent.run("Analiz\u00e1 t\u00e9cnicamente GGAL")
    state = repo.records[0][0]
    state.trace_events.append(
        {
            "event": "LLM_SUCCEEDED",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }
    )
    row = score_case(load_cases()[0], state, result, 10)
    settings = Settings(_env_file=None, llm_input_price_per_1m=2, llm_output_price_per_1m=4)
    assert aggregate([row], settings)["cost"] == pytest.approx(0.0004)
    state.trace_events[-1]["usage"] = {"prompt_tokens": 100}
    row = score_case(load_cases()[0], state, result, 10)
    assert row["output_tokens"] is None
    assert aggregate([row], settings)["cost"] is None


def test_repetitions_persist_separate_traces(tmp_path):
    case = copy.deepcopy(load_cases()[0])
    report, path = evaluate(
        Settings(_env_file=None), runs=2, fake=True, cases=[case], output_dir=tmp_path
    )
    assert path.exists()
    assert report["metrics"]["case_count"] == 1
    assert report["metrics"]["run_count"] == 2
    assert len({c["trace_id"] for c in report["cases"]}) == 2
    assert report["metrics"]["task_success_rate"] == 1
    assert "?" not in case["input"]
