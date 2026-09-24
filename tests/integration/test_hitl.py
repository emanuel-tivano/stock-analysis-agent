"""HITL uses real SQLite transactions; only market/LLM inputs are simulated."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from merval_agent.api.app import create_app
from merval_agent.config import Settings
from merval_agent.domain.actions import ApproveActionRequest, PendingAction
from merval_agent.domain.policy import MARKET_TIMEZONE
from merval_agent.memory.actions import ActionConflict
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


def test_pause_modify_approve_replay_and_restart_without_services(hitl):
    agent, client = hitl
    paused = propose(client)
    action_id = paused["pending_action"]["action_id"]
    initial = load(agent, action_id)
    assert initial.status == "PENDING" and initial.result is None
    assert initial.evidence_snapshot.report.technical.metrics.current_price == 160
    assert initial.evidence_snapshot.evaluated_at == HITL_AT
    assert initial.evidence_snapshot.evaluated_at <= initial.created_at
    # Restart the durable boundary and forbid any accidental provider/tool call.
    agent.repository = SQLiteRepository(agent.repository.path)
    agent.provider = None
    agent.tools = None
    response = client.post(
        url(paused, "modify"),
        json=body(
            changes={
                "focus": "momentum",
                "include_sections": ["momentum"],
                "review_note": "Revisión humana <script>",
            }
        ),
    )
    assert response.status_code == 200
    assert response.json()["action"]["status"] == "MODIFIED"
    assert response.json()["result"] is None
    modified = load(agent, action_id)
    assert modified.snapshot_sha256 == initial.snapshot_sha256
    assert modified.evidence_snapshot.evaluated_at == HITL_AT
    assert modified.updated_at >= initial.created_at
    approval = body(2, "approve-key-02")
    approved = client.post(url(paused, "approve"), json=approval)
    assert approved.status_code == 200, approved.text
    result = approved.json()["result"]
    assert result["status"] == "ANSWER"
    assert result["technical"] == initial.evidence_snapshot.report.technical.model_dump(mode="json")
    assert list(result["publication"]["sections"]) == ["momentum", "risk"]
    assert result["publication"]["editorial"]["review_note"] == "Revisión humana <script>"
    completed = load(agent, action_id)
    assert completed.evidence_snapshot.evaluated_at == HITL_AT
    assert completed.updated_at >= modified.updated_at
    replay = client.post(url(paused, "approve"), json=approval)
    assert replay.json() == approved.json()
    fetched = client.get(url(paused), params={"session_id": "hitl-session"})
    assert fetched.json()["result"] == result
    trace = agent.repository.get_trace(paused["trace_id"])
    events = [e["event"] for e in trace["events"] if e["event"].startswith("ACTION_")]
    assert events == [
        "ACTION_PROPOSED",
        "ACTION_PAUSED",
        "ACTION_MODIFIED",
        "ACTION_APPROVED",
        "ACTION_EXECUTED",
    ]
    assert trace["final_status"] == "ANSWER"


def test_reject_preserves_evidence_and_no_publication(hitl):
    agent, client = hitl
    p = propose(client, "Publicá un informe técnico de PAMP")
    response = client.post(url(p, "reject"), json=body(comment="No publicar"))
    assert response.status_code == 200
    assert response.json()["action"]["status"] == "REJECTED"
    assert response.json()["result"] is None
    assert client.post(url(p, "reject"), json=body(comment="No publicar")).json() == response.json()
    action = load(agent, p["pending_action"]["action_id"])
    assert action.evidence_snapshot.history.bars and action.resolved_at
    with sqlite3.connect(agent.repository.path) as db:
        assert db.execute("SELECT count(*) FROM report_publications").fetchone()[0] == 0
    for decision in ("approve", "modify", "reject"):
        request = body(key="another-key", **({"changes": {}} if decision == "modify" else {}))
        assert client.post(url(p, decision), json=request).status_code == 409


def test_conflicts_versions_keys_and_terminal_actions(hitl):
    _, client = hitl
    p = propose(client)
    modified = body(changes={"focus": "trend"})
    first = client.post(url(p, "modify"), json=modified)
    assert first.status_code == 200
    assert client.post(url(p, "modify"), json=modified).json() == first.json()
    assert client.post(url(p, "modify"), json=body(changes={"focus": "risk"})).status_code == 409
    assert client.post(url(p, "approve"), json=body(key="old-version")).status_code == 409
    assert client.post(url(p, "approve"), json=body(2, "new-version")).status_code == 200
    assert client.post(url(p, "approve"), json=body(2, "another-key")).status_code == 409
    assert client.post(url(p, "modify"), json=body(2, "yet-another", changes={})).status_code == 409


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
    p = propose(client)
    action_id = p["pending_action"]["action_id"]

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
    assert sum(e["event"] == "ACTION_EXECUTED" for e in events) == count


def test_rollback_if_finalization_fails(hitl, monkeypatch):
    agent, client = hitl
    p = propose(client)
    action_id = p["pending_action"]["action_id"]

    def fail(_):
        raise RuntimeError("controlled failure")

    monkeypatch.setattr("merval_agent.memory.actions.finalize", fail)
    with pytest.raises(RuntimeError):
        agent.repository.decide_action(action_id, "approve", ApproveActionRequest(**body()))
    assert load(agent, action_id).status == "PENDING"
    assert [e["event"] for e in agent.repository.get_action_events(action_id, "hitl-session")] == [
        "ACTION_PROPOSED",
        "ACTION_PAUSED",
    ]


def test_corrupt_snapshot_cannot_be_approved(hitl):
    agent, client = hitl
    p = propose(client)
    action_id = p["pending_action"]["action_id"]
    with sqlite3.connect(agent.repository.path) as db:
        raw = json.loads(db.execute("SELECT document FROM pending_actions").fetchone()[0])
        raw["evidence_snapshot"]["report"]["technical"]["metrics"]["current_price"] = 999
        db.execute(
            "UPDATE pending_actions SET document=? WHERE action_id=?", (json.dumps(raw), action_id)
        )
    response = client.post(url(p, "approve"), json=body())
    assert response.status_code == 409 and "integridad" in response.text
    assert "sqlite" not in response.text.lower()


def test_migrate_old_database(tmp_path):
    path = str(tmp_path / "old.sqlite3")
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE analyses(trace_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, timestamp TEXT NOT NULL,ticker TEXT,user_request TEXT NOT NULL,final_status TEXT NOT NULL,tool_trace TEXT NOT NULL,summary TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO analyses VALUES ('old','s','date','GGAL','private','ANSWER','[]','summary')"
        )
    repo = SQLiteRepository(path)
    assert repo.get_trace("old")["final_status"] == "ANSWER"
    SQLiteRepository(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM analyses").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM pending_actions").fetchone()[0] == 0


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
    p = propose(client)
    response = client.post(url(p, "approve"), json={**body(), **patch})
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
    p = propose(client)
    assert client.post(url(p, "modify"), json=body(changes=changes)).status_code == 422


def test_not_found_wrong_session_openapi_and_trace_privacy(hitl):
    agent, client = hitl
    p = propose(client)
    assert client.get(url(p), params={"session_id": "other"}).status_code == 404
    assert client.post(url(p, "approve"), json={**body(), "session_id": "other"}).status_code == 404
    assert client.post(f"/agent/actions/{uuid4()}/approve", json=body()).status_code == 404
    response = client.post(url(p, "approve"), json=body(comment="private human note"))
    assert "charset=utf-8" in response.headers["content-type"]
    events = client.get(url(p, "events"), params={"session_id": "hitl-session"}).json()
    assert all(e["payload_sha256"] and e["timestamp"] and e["actor"] for e in events)
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
    p = propose(client)
    action = load(agent, p["pending_action"]["action_id"])
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


def test_ordinary_analysis_and_ambiguous_remain_compatible(hitl):
    _, client = hitl
    result = client.post("/agent/run", json={"message": "Analizá técnicamente GGAL"}).json()
    assert result["status"] == "ANSWER" and result["pending_action"] is None
    result = client.post(
        "/agent/run", json={"message": "Prepará un informe técnico del banco"}
    ).json()
    assert result["status"] == "CLARIFY" and result["pending_action"] is None


@pytest.mark.parametrize("scenario", ["short", "failure"])
def test_unusable_market_never_creates_action(make_agent, tmp_path, payload, scenario):
    payload["data"] = payload["data"][:10]
    agent, _ = make_agent(data=payload, market_status=503 if scenario == "failure" else 200)
    agent.repository = SQLiteRepository(str(tmp_path / "failure.sqlite3"))
    result = agent.run("Prepará un informe técnico de GGAL")
    assert result.status in ("ERROR", "ABSTAIN") and result.pending_action is None
    with sqlite3.connect(agent.repository.path) as db:
        assert db.execute("SELECT count(*) FROM pending_actions").fetchone()[0] == 0


def test_chat_paused_projection(hitl):
    _, client = hitl
    r = client.post("/chat", json={"message": "Prepará un informe técnico de BMA"})
    assert r.status_code == 200
    assert r.json()["status"] == "PAUSED"
    assert r.json()["pending_action"]["ticker"] == "BMA"
    assert "evidence_snapshot" not in r.text


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
    p = propose(client)
    client.post(url(p, "approve"), json=body()).raise_for_status()
    action = load(agent, p["pending_action"]["action_id"])
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
    p = propose(client)

    def fail(_):
        raise RuntimeError("private stack diagnostic")

    monkeypatch.setattr("merval_agent.memory.actions.finalize", fail)
    with TestClient(
        create_app(agent, Settings(_env_file=None)), raise_server_exceptions=False
    ) as safe_client:
        response = safe_client.post(url(p, "approve"), json=body())
    assert response.status_code == 500
    assert "private" not in response.text and "Traceback" not in response.text
    assert "No se pudo" in response.json()["detail"]
    assert load(agent, p["pending_action"]["action_id"]).status == "PENDING"


def test_proposal_history_retains_each_editorial_version(hitl):
    agent, client = hitl
    p = propose(client)
    client.post(
        url(p, "modify"), json=body(changes={"focus": "trend", "review_note": "primera"})
    ).raise_for_status()
    client.post(
        url(p, "modify"),
        json=body(2, "second-change", changes={"focus": "risk", "review_note": "segunda"}),
    ).raise_for_status()
    with sqlite3.connect(agent.repository.path) as db:
        values = [
            json.loads(r[0])
            for r in db.execute("SELECT proposal FROM action_events ORDER BY event_id")
        ]
    assert [v["review_note"] for v in values] == ["", "", "primera", "segunda"]
