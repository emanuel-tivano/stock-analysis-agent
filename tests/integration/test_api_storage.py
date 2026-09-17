import sqlite3

from fastapi.testclient import TestClient

from merval_agent.api.app import create_app
from merval_agent.config import Settings
from merval_agent.memory.sqlite import SQLiteRepository


def test_api_lifespan_health_and_run(make_agent, tmp_path):
    agent, _ = make_agent()
    agent.repository = SQLiteRepository(str(tmp_path / "sessions.sqlite3"))
    with TestClient(create_app(agent=agent)) as client:
        assert client.get("/health").json()["status"] == "ok"
        response = client.post(
            "/agent/run", json={"message": "Técnico GGAL", "session_id": "session-1"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ANSWER"
        assert body["session_id"] == "session-1"
        assert client.post("/agent/run", json={"message": ""}).status_code == 422
        assert client.post("/agent/run", json={"message": "  "}).status_code == 422
        client.post("/agent/run", json={"message": "Galicia", "session_id": "session-1"})
    with sqlite3.connect(tmp_path / "sessions.sqlite3") as db:
        rows = db.execute(
            "SELECT final_status, tool_trace FROM analyses ORDER BY timestamp"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][0] == "ANSWER"
        assert "get_market_history" in rows[0][1]


def test_default_composition_starts_without_network(tmp_path):
    with TestClient(
        create_app(
            settings=Settings(llm_provider="fake", database_path=str(tmp_path / "db.sqlite3"))
        )
    ) as client:
        assert client.get("/health").status_code == 200
        assert client.post("/agent/run", json={"message": "XXXX"}).json()["status"] == "CLARIFY"


def test_api_terminal_contracts(make_agent):
    from merval_agent.adapters.llm.fake import FakeLLMProvider
    from merval_agent.domain.errors import ExternalServiceError

    def failure(state):
        raise ExternalServiceError("private")

    cases = [
        (None, 200, "technical GGAL", "ANSWER"),
        (None, 200, "XXXX", "CLARIFY"),
        (None, 503, "technical GGAL", "ERROR"),
        (FakeLLMProvider(failure), 200, "GGAL", "ERROR"),
    ]
    for provider, code, message, expected in cases:
        agent, _ = make_agent(provider=provider, market_status=code)
        with TestClient(create_app(agent=agent)) as client:
            response = client.post(
                "/agent/run", json={"message": message, "session_id": "contract"}
            )
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == expected
            assert body["session_id"] == "contract" and body["trace_id"]
            assert "trace_events" not in body
