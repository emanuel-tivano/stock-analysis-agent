import json
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from merval_agent.api.app import create_app
from merval_agent.memory.sqlite import SQLiteRepository


@pytest.mark.parametrize(
    "message,market_status,status,ticker,tools",
    [
        (
            "Analizá técnicamente GGAL",
            200,
            "ANSWER",
            "GGAL",
            [
                "resolve_asset",
                "get_market_history",
                "calculate_technical_indicators",
                "search_methodology",
            ],
        ),
        (
            "Analizá los fundamentos de PAMP",
            200,
            "ABSTAIN",
            "PAMP",
            ["resolve_asset", "get_latest_financial_statement", "search_methodology"],
        ),
        ("Analizá XXXX", 200, "CLARIFY", None, ["resolve_asset"]),
        (
            "Analizá técnicamente GGAL según Murphy",
            200,
            "ABSTAIN",
            "GGAL",
            [
                "resolve_asset",
                "get_market_history",
                "calculate_technical_indicators",
                "search_methodology",
            ],
        ),
        (
            "Analizá técnicamente GGAL",
            503,
            "ABSTAIN",
            "GGAL",
            ["resolve_asset", "get_market_history", "search_methodology"],
        ),
    ],
)
def test_golden_trace(make_agent, tmp_path, message, market_status, status, ticker, tools):
    agent, memory = make_agent(market_status=market_status)
    result = agent.run(message)
    state = memory.records[-1][0]
    repo = SQLiteRepository(str(tmp_path / "golden.sqlite3"))
    repo.save(state, result)
    trace = repo.get_trace(result.trace_id)
    assert result.status == trace["final_status"] == status
    assert result.ticker == trace["ticker"] == ticker
    assert trace["session_id"] == result.session_id
    assert trace["timestamp"]
    assert [e["tool_name"] for e in trace["events"] if e["event"] == "TOOL_STARTED"] == tools
    expected = [("AGENT_STARTED", 0)]
    for step, tool in enumerate(tools, 1):
        expected.extend(
            [
                (name, step)
                for name in (
                    "DECISION_MADE",
                    "TOOL_STARTED",
                    "TOOL_FAILED"
                    if market_status != 200 and tool == "get_market_history"
                    else "TOOL_SUCCEEDED",
                    "STATE_UPDATED",
                )
            ]
        )
    last = len(tools) + 1
    expected.extend([(name, last) for name in ("DECISION_MADE", "STATE_UPDATED", "STATE_UPDATED")])
    if status == "ABSTAIN":
        expected.append(("AGENT_ABSTAINED", last))
    expected.append(("AGENT_FINISHED", last))
    assert [(e["event"], e["step"]) for e in trace["events"]] == expected
    for event in trace["events"]:
        assert event["trace_id"] == result.trace_id
        assert "outcome" in event and "state" in event
    if "get_market_history" in tools:
        call = next(c for c in state.tool_calls if c.name == "get_market_history")
        assert call.arguments["range"] == "6M"
        assert result.fundamental.status == "NOT_REQUESTED"
        assert result.technical.status == "INSUFFICIENT_DATA"
        assert "technical" in result.data_quality.abstentions
    if market_status != 200:
        failure = next(e for e in trace["events"] if e["event"] == "TOOL_FAILED")
        assert failure["error"] == "EXTERNAL_SERVICE"
        assert failure["latency_ms"] >= 0
        assert any(not o.success for o in state.observations)
    if "search_methodology" in tools:
        search = next(
            e
            for e in trace["events"]
            if e["event"] == "TOOL_STARTED" and e["tool_name"] == "search_methodology"
        )
        assert search["arguments"]["source"] == ("graham" if ticker == "PAMP" else "murphy")
        evidence = result.technical.evidence + result.fundamental.evidence
        assert any(e.kind == "DEMO" for e in evidence)
    cli = subprocess.run(
        [sys.executable, "scripts/show_trace.py", result.trace_id, "--database", repo.path],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "AGENT_FINISHED" in cli.stdout
    assert message not in cli.stdout
    assert repo.get_trace("missing") is None


def test_api_utf8_and_docs(make_agent):
    agent, repo = make_agent()
    text = "Analizá técnicamente GGAL á é í ó ú ñ ¿"
    with TestClient(create_app(agent=agent)) as client:
        response = client.post(
            "/agent/run",
            content=json.dumps({"message": text}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"
        raw = response.content.decode("utf-8", errors="strict")
        for expected in ("Métricas técnicas", "conclusión", "Metodología"):
            assert expected in raw
            assert expected.encode("utf-8") in response.content
        assert repo.records[-1][0].user_request == text
        assert client.get("/docs").status_code == 200
        assert "SwaggerUIBundle" in client.get("/docs").text
        assert "/agent/run" in client.get("/openapi.json").json()["paths"]
