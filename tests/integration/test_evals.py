import json
from pathlib import Path
from time import perf_counter

import pytest

CASES = [
    json.loads(line)
    for line in (Path(__file__).parents[2] / "evals/dataset.jsonl")
    .read_text(encoding="utf-8")
    .splitlines()
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_eval(case, make_agent, eval_report):
    agent, repo = make_agent(market_status=case.get("market_status", 200))
    started = perf_counter()
    result = agent.run(case["input"])
    state = repo.records[-1][0]
    labels = [
        c.name + (":" + c.arguments["source"] if c.name == "search_methodology" else "")
        for c in state.tool_calls
    ]
    missing = set(case["expected_tools"]) - set(labels)
    unnecessary = [x for x in labels if x in case["forbidden_tools"]]
    success = (
        not missing
        and not unnecessary
        and result.status in case["expected_status"]
        and result.ticker == case.get("expected_asset")
        and set(case.get("expected_abstention", [])) <= set(result.data_quality.abstentions)
    )
    eval_report.append(
        {
            "passed": bool(success),
            "tools_correct": not missing and not unnecessary,
            "violations": len(unnecessary),
            "steps": state.iteration_count,
        }
    )
    print(
        json.dumps(
            {
                "id": case["id"],
                "task_success": success,
                "tool_selection_accuracy": len(set(labels) & set(case["expected_tools"]))
                / max(1, len(set(labels))),
                "unnecessary_tool_calls": len(unnecessary),
                "steps": state.iteration_count,
                "latency_ms": (perf_counter() - started) * 1000,
                "errors": len(result.errors),
                "abstention_correctness": result.status in case["expected_status"],
            }
        )
    )
    assert success, {"missing": missing, "unnecessary": unnecessary, "status": result.status}


@pytest.fixture(scope="module")
def eval_report():
    rows = []
    yield rows
    print(
        json.dumps(
            {
                "cases": len(rows),
                "passed": sum(r["passed"] for r in rows),
                "failed": sum(not r["passed"] for r in rows),
                "tool_selection_accuracy": sum(r["tools_correct"] for r in rows)
                / max(1, len(rows)),
                "forbidden_tool_violations": sum(r["violations"] for r in rows),
                "average_steps": sum(r["steps"] for r in rows) / max(1, len(rows)),
            }
        )
    )
