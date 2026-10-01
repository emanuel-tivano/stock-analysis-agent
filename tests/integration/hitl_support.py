import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from merval_agent.api.app import create_app
from merval_agent.config import Settings
from merval_agent.domain.actions import PendingAction
from merval_agent.domain.policy import MARKET_TIMEZONE
from merval_agent.memory.sqlite import SQLiteRepository

HITL_AT = datetime(2020, 1, 15, 15, tzinfo=UTC)


@pytest.fixture
def hitl(make_agent, tmp_path, payload):
    payload = json.loads(json.dumps(payload))
    payload["fetchedAt"] = (HITL_AT - timedelta(seconds=1)).isoformat()
    today = HITL_AT.astimezone(MARKET_TIMEZONE).date()
    for i, row in enumerate(payload["data"]):
        row["date"] = str(today - timedelta(days=59 - i))
    agent, _ = make_agent(data=payload, clock=lambda: HITL_AT)
    agent.repository = SQLiteRepository(str(tmp_path / "hitl.sqlite3"))
    with TestClient(create_app(agent, Settings(_env_file=None))) as client:
        yield agent, client


def propose(client, message="Prepará un informe técnico de GGAL para revisión."):
    response = client.post("/agent/run", json={"message": message, "session_id": "hitl-session"})
    assert response.status_code == 200
    assert response.json()["status"] == "PAUSED", response.text
    return response.json()


def body(version=1, key="test-key-0001", **kwargs):
    return {
        "session_id": "hitl-session",
        "expected_version": version,
        "idempotency_key": key,
        **kwargs,
    }


def url(result, decision=""):
    return (
        "/agent/actions/"
        + result["pending_action"]["action_id"]
        + ("/" + decision if decision else "")
    )


def load(agent, action_id):
    with sqlite3.connect(agent.repository.path) as db:
        raw = db.execute(
            "SELECT document FROM pending_actions WHERE action_id=?", (action_id,)
        ).fetchone()[0]
    return PendingAction.model_validate_json(raw)
