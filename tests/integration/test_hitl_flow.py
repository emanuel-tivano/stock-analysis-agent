"""Happy paths and public compatibility for the HITL workflow."""

import json
import sqlite3

import pytest

from merval_agent.memory.sqlite import SQLiteRepository

from .hitl_support import HITL_AT, body, hitl, load, propose, url

__all__ = ["hitl"]


def test_pause_modify_approve_replay_and_restart_without_services(hitl):
    agent, client = hitl
    paused = propose(client)
    action_id = paused["pending_action"]["action_id"]
    initial = load(agent, action_id)
    assert initial.status == "PENDING" and initial.result is None
    assert initial.evidence_snapshot.report.technical.metrics.current_price == 160
    assert initial.evidence_snapshot.evaluated_at == HITL_AT
    assert initial.evidence_snapshot.evaluated_at <= initial.created_at
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
    result = propose(client, "Publicá un informe técnico de PAMP")
    response = client.post(url(result, "reject"), json=body(comment="No publicar"))
    assert response.status_code == 200
    assert response.json()["action"]["status"] == "REJECTED"
    assert response.json()["result"] is None
    assert (
        client.post(url(result, "reject"), json=body(comment="No publicar")).json()
        == response.json()
    )
    action = load(agent, result["pending_action"]["action_id"])
    assert action.evidence_snapshot.history.bars and action.resolved_at
    with sqlite3.connect(agent.repository.path) as db:
        assert db.execute("SELECT count(*) FROM report_publications").fetchone()[0] == 0
    for decision in ("approve", "modify", "reject"):
        request = body(key="another-key", **({"changes": {}} if decision == "modify" else {}))
        assert client.post(url(result, decision), json=request).status_code == 409


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
    response = client.post("/chat", json={"message": "Prepará un informe técnico de BMA"})
    assert response.status_code == 200
    assert response.json()["status"] == "PAUSED"
    assert response.json()["pending_action"]["ticker"] == "BMA"
    assert "evidence_snapshot" not in response.text


def test_proposal_history_retains_each_editorial_version(hitl):
    agent, client = hitl
    result = propose(client)
    client.post(
        url(result, "modify"),
        json=body(changes={"focus": "trend", "review_note": "primera"}),
    ).raise_for_status()
    client.post(
        url(result, "modify"),
        json=body(2, "second-change", changes={"focus": "risk", "review_note": "segunda"}),
    ).raise_for_status()
    with sqlite3.connect(agent.repository.path) as db:
        values = [
            json.loads(row[0])
            for row in db.execute("SELECT proposal FROM action_events ORDER BY event_id")
        ]
    assert [value["review_note"] for value in values] == ["", "", "primera", "segunda"]
