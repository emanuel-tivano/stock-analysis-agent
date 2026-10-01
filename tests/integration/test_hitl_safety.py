"""Conflict, integrity, rollback and privacy checks for HITL."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from merval_agent.api.app import create_app
from merval_agent.config import Settings
from merval_agent.domain.actions import ApproveActionRequest, PendingAction
from merval_agent.memory.actions import ActionConflict
from merval_agent.memory.sqlite import SQLiteRepository

from .hitl_support import body, hitl, load, propose, url

__all__ = ["hitl"]


def test_conflicts_versions_keys_and_terminal_actions(hitl):
    _, client = hitl
    result = propose(client)
    modified = body(changes={"focus": "trend"})
    first = client.post(url(result, "modify"), json=modified)
    assert first.status_code == 200
    assert client.post(url(result, "modify"), json=modified).json() == first.json()
    assert client.post(url(result, "modify"), json=body(changes={"focus": "risk"})).status_code == 409
    assert client.post(url(result, "approve"), json=body(key="old-version")).status_code == 409
    assert client.post(url(result, "approve"), json=body(2, "new-version")).status_code == 200
    assert client.post(url(result, "approve"), json=body(2, "another-key")).status_code == 409
    assert (
        client.post(url(result, "modify"), json=body(2, "yet-another", changes={})).status_code
        == 409
    )


@pytest.mark.parametrize(
    "decisions,keys",
    [
        (("approve", "approve"), ("same-key-00", "same-key-00")),
        (("approve", "approve"), ("first-key-0", "second-key")),
        (("approve", "reject"), ("first-key-0", "second-key")),
    ],
)
def test_concurrent_requests_use_database_lock(hitl, decisions, keys):
    agent, client = hitl
    result = propose(client)
    action_id = result["pending_action"]["action_id"]

    def execute(args):
        decision, key = args
        repo = SQLiteRepository(agent.repository.path)
        try:
            return repo.decide_action(
                action_id, decision, ApproveActionRequest(**body(key=key))
            ).action.status
        except ActionConflict:
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(execute, zip(decisions, keys)))
    with sqlite3.connect(agent.repository.path) as db:
        count = db.execute("SELECT count(*) FROM report_publications").fetchone()[0]
    assert count <= 1
    if decisions == ("approve", "approve"):
        assert count == 1
        assert outcomes.count("EXECUTED") == (2 if keys[0] == keys[1] else 1)
    else:
        assert outcomes.count("CONFLICT") == 1
    events = agent.repository.get_action_events(action_id, "hitl-session")
    assert sum(event["event"] == "ACTION_EXECUTED" for event in events) == count


def test_rollback_if_finalization_fails(hitl, monkeypatch):
    agent, client = hitl
    result = propose(client)
    action_id = result["pending_action"]["action_id"]

    def fail(_):
        raise RuntimeError("controlled failure")

    monkeypatch.setattr("merval_agent.domain.actions.finalize", fail)
    with pytest.raises(RuntimeError):
        agent.repository.decide_action(action_id, "approve", ApproveActionRequest(**body()))
    assert load(agent, action_id).status == "PENDING"
    assert [
        event["event"] for event in agent.repository.get_action_events(action_id, "hitl-session")
    ] == ["ACTION_PROPOSED", "ACTION_PAUSED"]


def test_corrupt_snapshot_cannot_be_approved(hitl):
    agent, client = hitl
    result = propose(client)
    action_id = result["pending_action"]["action_id"]
    with sqlite3.connect(agent.repository.path) as db:
        raw = json.loads(db.execute("SELECT document FROM pending_actions").fetchone()[0])
        raw["evidence_snapshot"]["report"]["technical"]["metrics"]["current_price"] = 999
        db.execute(
            "UPDATE pending_actions SET document=? WHERE action_id=?", (json.dumps(raw), action_id)
        )
    response = client.post(url(result, "approve"), json=body())
    assert response.status_code == 409 and "integridad" in response.text
    assert "sqlite" not in response.text.lower()


@pytest.mark.parametrize(
    "patch",
    [
        {"expected_version": 0},
        {"expected_version": True},
        {"expected_version": "1"},
        {"idempotency_key": "short"},
        {"idempotency_key": "x" * 101},
        {"idempotency_key": "bad key value"},
        {"comment": "x" * 501},
        {"ticker": "BMA"},
        {"session_id": "bad session"},
    ],
)
def test_invalid_api_request(hitl, patch):
    _, client = hitl
    result = propose(client)
    response = client.post(url(result, "approve"), json={**body(), **patch})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "changes",
    [
        {"current_price": 1},
        {"ticker": "BMA"},
        {"focus": "fundamental"},
        {"include_sections": []},
        {"include_sections": ["overview", "overview"]},
        {"review_note": "x" * 501},
        {"review_note": "\u0000"},
        {"focus": "trend", "include_sections": ["risk"]},
        {"include_sections": ["prices"]},
    ],
)
def test_editorial_contract_rejects_financial_changes(hitl, changes):
    _, client = hitl
    result = propose(client)
    assert client.post(url(result, "modify"), json=body(changes=changes)).status_code == 422


def test_not_found_wrong_session_openapi_and_trace_privacy(hitl):
    agent, client = hitl
    result = propose(client)
    assert client.get(url(result), params={"session_id": "other"}).status_code == 404
    assert (
        client.post(url(result, "approve"), json={**body(), "session_id": "other"}).status_code
        == 404
    )
    assert client.post(f"/agent/actions/{uuid4()}/approve", json=body()).status_code == 404
    response = client.post(url(result, "approve"), json=body(comment="private human note"))
    assert "charset=utf-8" in response.headers["content-type"]
    events = client.get(url(result, "events"), params={"session_id": "hitl-session"}).json()
    assert all(event["payload_sha256"] and event["timestamp"] and event["actor"] for event in events)
    raw = json.dumps(events)
    assert "private human note" not in raw and "test-key-0001" not in raw
    schema = client.get("/openapi.json").json()
    for name in (
        "ApproveActionRequest",
        "ModifyActionRequest",
        "RejectActionRequest",
        "PendingActionResponse",
        "ActionDecisionResponse",
    ):
        assert name in schema["components"]["schemas"]
    for decision in ("approve", "modify", "reject"):
        assert f"/agent/actions/{{action_id}}/{decision}" in schema["paths"]


def test_state_and_timestamp_validation(hitl):
    agent, client = hitl
    result = propose(client)
    action = load(agent, result["pending_action"]["action_id"])
    for change in (
        {"created_at": "2026-01-01T00:00:00"},
        {"updated_at": action.created_at - timedelta(seconds=1)},
        {"status": "EXECUTED"},
        {"status": "APPROVED"},
        {"resolved_at": action.updated_at},
        {"status": "REJECTED"},
    ):
        with pytest.raises(ValidationError):
            PendingAction.model_validate({**action.model_dump(), **change})


def test_proposal_and_trace_rollback_together(hitl, monkeypatch):
    agent, client = hitl

    def fail(db, action):
        raise sqlite3.OperationalError("sensitive internal diagnostic")

    monkeypatch.setattr("merval_agent.memory.sqlite.insert_action", fail)
    result = client.post(
        "/agent/run", json={"message": "Prepará un informe técnico de GGAL"}
    ).json()
    assert result["status"] == "ERROR" and result["pending_action"] is None
    assert "sensitive" not in json.dumps(result)
    with sqlite3.connect(agent.repository.path) as db:
        assert db.execute("SELECT count(*) FROM analyses").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM pending_actions").fetchone()[0] == 0


def test_approved_payload_and_published_evidence_cannot_drift(hitl):
    agent, client = hitl
    result = propose(client)
    client.post(url(result, "approve"), json=body()).raise_for_status()
    action = load(agent, result["pending_action"]["action_id"])
    changed = action.model_dump()
    changed["proposed_payload"]["focus"] = "momentum"
    with pytest.raises(ValidationError):
        PendingAction.model_validate(changed)
    changed = action.model_dump()
    changed["result"]["technical"]["metrics"]["current_price"] += 1
    with pytest.raises(ValidationError):
        PendingAction.model_validate(changed)


def test_http_internal_failure_is_generic_and_rolls_back(hitl, monkeypatch):
    agent, client = hitl
    result = propose(client)

    def fail(_):
        raise RuntimeError("private stack diagnostic")

    monkeypatch.setattr("merval_agent.domain.actions.finalize", fail)
    with TestClient(
        create_app(agent, Settings(_env_file=None)), raise_server_exceptions=False
    ) as safe_client:
        response = safe_client.post(url(result, "approve"), json=body())
    assert response.status_code == 500
    assert "private" not in response.text and "Traceback" not in response.text
    assert "No se pudo" in response.json()["detail"]
    assert load(agent, result["pending_action"]["action_id"]).status == "PENDING"
