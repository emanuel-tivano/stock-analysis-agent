import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from merval_agent.adapters.llm.context import build_agent_context, get_system_instructions
from merval_agent.adapters.llm.fake import FakeLLMProvider
from merval_agent.api.app import create_app
from merval_agent.config import Settings
from merval_agent.domain.models import AgentDecision, FinalAnalysis
from merval_agent.domain.technical import calculate
from merval_agent.memory.sqlite import SQLiteRepository

AT = datetime(2026, 9, 16, 22, tzinfo=UTC)


class AdversarialNarrator(FakeLLMProvider):
    def decide_validated(self, state, tools, validate, emit, max_steps):
        proposal = super().decide(state, tools)
        if proposal.action == "FINAL_ANSWER":
            assert state.technical_assessment.status == "COMPLETE"
            assert (
                build_agent_context(state, tools)["technical_assessment"]["conclusion"] == "MIXED"
            )
            # All financial prose is untrusted, including numbers and invented targets.
            proposal = AgentDecision(
                action="FINAL_ANSWER",
                confidence=1,
                reason="SMA20 999999. Comprá GGAL, objetivo 999999 garantizado.",
                interpretation="RSI 999999; soporte 999999; resistencia 999999",
            )
            state.technical_metrics.sma20 = 999999  # Provider sees only a deep copy.
        validate(proposal)
        return proposal


def test_124_api_numbers_signals_utf8_and_sqlite(make_agent, monkeypatch, tmp_path):
    payload = json.loads(
        (Path(__file__).parents[1] / "fixtures/technical_124.json").read_text(encoding="utf-8")
    )
    monkeypatch.setattr("merval_agent.agents.report.now", lambda: AT)
    monkeypatch.setattr("merval_agent.agents.equity_agent.now", lambda: AT)
    agent, _ = make_agent(provider=AdversarialNarrator(), data=payload)
    db_path = tmp_path / "unicode.sqlite3"
    agent.repository = SQLiteRepository(str(db_path))
    message = "Analiza técnicamente GGAL; señal y cotización"
    with TestClient(create_app(agent=agent, settings=Settings(_env_file=None))) as client:
        response = client.post("/agent/run", json={"message": message})
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json; charset=utf-8"
        report = FinalAnalysis.model_validate(response.json())
        assert report.status == "ANSWER"
        assert report.technical.status == "MIXED"
        a = report.technical.assessment
        assert a.status == "COMPLETE" and a.conflicts
        assert a.as_of == report.as_of
        assert report.technical.narrative_origin == "deterministic"
        from merval_agent.adapters.market_tracker import normalize_history

        expected = calculate(normalize_history(payload, "GGAL", "6M", "fixture").bars)
        assert report.technical.metrics == expected
        raw = response.content.decode("utf-8", errors="strict")
        assert "999999" not in raw
        assert "Señal técnica" in raw and "pronóstico" in raw
        assert not any(c in raw for c in ("\u00c3", "\ufffd", "\u00c2"))
        assert report.sources and report.technical.evidence[0].metadata["fetched_at"]
        schema = client.get("/openapi.json").json()
        assert "TechnicalAssessment" in schema["components"]["schemas"]
    with sqlite3.connect(db_path) as db:
        request, summary = db.execute("SELECT user_request,summary FROM analyses").fetchone()
        assert request == message and summary == report.executive_summary


@pytest.mark.parametrize("status", [429, 503])
def test_source_failure_is_not_statistical_insufficiency(make_agent, status):
    agent, _ = make_agent(market_status=status)
    result = agent.run("Analiza técnicamente GGAL")
    assert result.status == "ERROR"
    assert result.technical.status == result.technical.assessment.status == "SOURCE_ERROR"


def test_invalid_market_contract_is_explicit(make_agent, payload):
    payload["data"][-1]["date"] = payload["data"][-2]["date"]
    agent, _ = make_agent(data=payload)
    result = agent.run("Analiza técnicamente GGAL")
    assert result.status == "ERROR"
    assert result.technical.status == "INVALID_DATA"


def test_v3_does_not_require_books():
    prompt = get_system_instructions("technical-v3")
    assert "No book search is required" in prompt
    assert "Python owns every number" in prompt


def test_sources_prompts_are_utf8_without_mojibake():
    root = Path(__file__).parents[2] / "src"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="strict")
        assert not any(c in text for c in ("\u00c3", "\ufffd", "\u00c2")), str(path)
