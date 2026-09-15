import json
import sqlite3

from merval_agent.adapters.llm.fake import FakeLLMProvider
from merval_agent.domain.errors import ExternalServiceError
from merval_agent.memory.sqlite import SQLiteRepository


def test_invalid_decision_recovery_keeps_trace_steps(make_agent, tmp_path):
    def script(state):
        if state.iteration_count == 1:
            return {"action": "INVALID"}
        if state.iteration_count == 2:
            return {
                "action": "CALL_TOOL",
                "tool_name": "resolve_asset",
                "tool_args": {"query": "GGAL"},
                "reason": "recover",
                "confidence": 1,
            }
        return {"action": "ABSTAIN", "reason": "No evidence", "confidence": 1}

    agent, _ = make_agent(provider=FakeLLMProvider(script))
    path = str(tmp_path / "trace.sqlite3")
    agent.repository = SQLiteRepository(path)
    assert agent.run("GGAL").status == "ABSTAIN"
    with sqlite3.connect(path) as db:
        trace = json.loads(db.execute("SELECT tool_trace FROM analyses").fetchone()[0])
    assert trace[0]["step"] == 2
    assert trace[0]["success"] is True


def test_provider_error_distinct_from_abstention(make_agent):
    def fail(state):
        raise ExternalServiceError("test")

    agent, _ = make_agent(provider=FakeLLMProvider(fail))
    result = agent.run("GGAL")
    assert result.status == "ERROR"
    assert result.errors[0].code == "LLM_FAILURE"


def test_persistence_failure_explicit(make_agent):
    class BrokenRepository:
        def save(self, state, result):
            raise OSError("test")

    agent, _ = make_agent()
    agent.repository = BrokenRepository()
    result = agent.run("XXXX")
    assert result.status == "ERROR"
    assert result.errors[-1].code == "PERSISTENCE_FAILURE"


def test_final_answer_requires_resolved_asset(make_agent):
    agent, repo = make_agent(
        provider=FakeLLMProvider(
            lambda s: {"action": "FINAL_ANSWER", "reason": "premature", "confidence": 1}
        ),
        max_steps=2,
    )
    result = agent.run("GGAL")
    assert result.status == "ABSTAIN"
    state = repo.records[0][0]
    assert state.iteration_count == 2
    assert all(o.error.code == "INVALID_DECISION" for o in state.observations)
    assert [e["step"] for e in state.trace_events if e["event"] == "DECISION_MADE"] == [1, 2]


def test_final_answer_without_data_is_limited(make_agent):
    def script(state):
        if not state.resolved_asset:
            return {
                "action": "CALL_TOOL",
                "tool_name": "resolve_asset",
                "tool_args": {"query": "GGAL"},
                "reason": "resolve",
                "confidence": 1,
            }
        return {"action": "FINAL_ANSWER", "reason": "premature", "confidence": 1}

    agent, _ = make_agent(provider=FakeLLMProvider(script))
    assert agent.run("GGAL").status == "ABSTAIN"


def test_trace_migrates_legacy_schema(tmp_path, make_agent):
    from merval_agent.memory.sqlite import read_trace

    path = str(tmp_path / "legacy.sqlite3")
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE analyses (trace_id TEXT PRIMARY KEY, session_id TEXT, timestamp TEXT, "
            "ticker TEXT, user_request TEXT, final_status TEXT, tool_trace TEXT, summary TEXT)"
        )
        db.execute(
            "INSERT INTO analyses VALUES ('old', 's', 't', NULL, 'private', 'CLARIFY', '[]', 'summary')"
        )
    assert read_trace(path, "old")["events"] == []
    repo = SQLiteRepository(path)
    agent, _ = make_agent()
    agent.repository = repo
    result = agent.run("XXXX")
    assert repo.get_trace(result.trace_id)["events"][-1]["event"] == "AGENT_FINISHED"
    assert repo.get_trace("old")["final_status"] == "CLARIFY"


def test_persisted_events_exclude_free_text(make_agent, tmp_path):
    agent, _ = make_agent()
    agent.repository = SQLiteRepository(str(tmp_path / "privacy.sqlite3"))
    result = agent.run("GGAL secret-test-123")
    trace = agent.repository.get_trace(result.trace_id)
    assert "secret-test-123" not in json.dumps(trace)
    assert "user_request" not in trace and "summary" not in trace


def test_repository_closes_connections(make_agent, tmp_path, monkeypatch):
    original = sqlite3.connect
    connections = []

    def connect(*args, **kwargs):
        db = original(*args, **kwargs)
        connections.append(db)
        return db

    monkeypatch.setattr(sqlite3, "connect", connect)
    repo = SQLiteRepository(str(tmp_path / "closed.sqlite3"))
    agent, _ = make_agent()
    agent.repository = repo
    result = agent.run("XXXX")
    assert repo.get_trace(result.trace_id)
    assert len(connections) == 3
    for db in connections:
        import pytest

        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            db.execute("SELECT 1")
