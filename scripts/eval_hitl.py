"""Versioned offline HITL matrix. SQLite/API are real; market and decisions are Fake."""

import hashlib
import json
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from smoke_api import market_payload

from merval_agent.api.app import create_app
from merval_agent.bootstrap import build_agent
from merval_agent.config import Settings
from merval_agent.domain.actions import ApproveActionRequest
from merval_agent.memory.actions import ActionConflict
from merval_agent.memory.sqlite import SQLiteRepository


def evaluate(output: Path | None = None):
    logging.basicConfig(level=logging.WARNING)
    dataset = Path(__file__).resolve().parents[1] / "evals/hitl_v1_dataset.jsonl"
    output = output or Path("evals/results") / (
        "hitl-v1-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    )
    output.mkdir(parents=True, exist_ok=False)
    cases = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines()]
    checks = {
        k: []
        for k in (
            "proposal_accuracy",
            "pause_before_execution",
            "approval_success",
            "modification_validation",
            "rejection_success",
            "trace_completeness",
            "recovery_after_restart",
        )
    }
    duplicates = stale_rejections = 0
    records = []
    for case in cases:
        counts_before = {k: len(v) for k, v in checks.items()}
        scenario = case["scenario"]
        calls = []

        def handle(request):
            calls.append(str(request.url))
            if scenario != "error" and request.url.path.endswith("/history"):
                return httpx.Response(
                    200,
                    json=market_payload(case["ticker"], "6M", 10 if scenario == "short" else 60),
                )
            return httpx.Response(503, json={"ok": False})

        settings = Settings(
            _env_file=None,
            llm_provider="fake",
            llm_api_key="",
            llm_model="",
            market_tracker_base_url="https://synthetic-market.test",
            bolsar_base_url="https://synthetic-documents.test",
            database_path=str(output / (case["id"] + ".sqlite3")),
        )
        with httpx.Client(transport=httpx.MockTransport(handle)) as upstream:
            agent = build_agent(settings, upstream)
            with TestClient(create_app(agent, settings)) as client:
                message = f"Prepará un informe técnico de {case['ticker'] or 'Grupo Financiero Galicia'} para revisión."
                proposed = client.post(
                    "/agent/run", json={"message": message, "session_id": "eval-hitl"}
                ).json()
                expected = (
                    "CLARIFY"
                    if scenario == "ambiguous"
                    else "ERROR"
                    if scenario == "error"
                    else "ABSTAIN"
                    if scenario == "short"
                    else "PAUSED"
                )
                case_checks = [proposed["status"] == expected]
                checks["proposal_accuracy"].append(case_checks[-1])
                record = {
                    "case": case,
                    "mode": "OFFLINE_FAKE",
                    "proposal": proposed,
                    "decisions": [],
                }
                if expected == "PAUSED" and proposed["status"] == "PAUSED":
                    action_id = proposed["pending_action"]["action_id"]
                    endpoint = "/agent/actions/" + action_id
                    db_path = agent.repository.path
                    with sqlite3.connect(db_path) as db:
                        checks["pause_before_execution"].append(
                            db.execute("SELECT count(*) FROM report_publications").fetchone()[0]
                            == 0
                        )
                    upstream_before = len(calls)
                    request = {
                        "session_id": "eval-hitl",
                        "expected_version": 1,
                        "idempotency_key": "eval-decision-01",
                    }

                    def decide(kind, data):
                        response = client.post(endpoint + "/" + kind, json=data)
                        record["decisions"].append(
                            {
                                "decision": kind,
                                "request": data,
                                "http_status": response.status_code,
                                "response": response.json(),
                            }
                        )
                        return response

                    if scenario in ("modify_approve", "stale"):
                        changed = decide(
                            "modify",
                            {
                                **request,
                                "changes": {"focus": "momentum", "review_note": "Revisión humana"},
                            },
                        )
                        checks["modification_validation"].append(
                            changed.status_code == 200
                            and changed.json()["action"]["version"] == 2
                            and changed.json()["result"] is None
                        )
                        invalid = decide(
                            "modify",
                            {
                                **request,
                                "idempotency_key": "invalid-edit",
                                "expected_version": 2,
                                "changes": {"ticker": "ALUA"},
                            },
                        )
                        checks["modification_validation"].append(invalid.status_code == 422)
                        if scenario == "stale":
                            stale = decide(
                                "modify",
                                {
                                    **request,
                                    "idempotency_key": "stale-edit",
                                    "changes": {"focus": "risk"},
                                },
                            )
                            stale_rejections += stale.status_code == 409
                            case_checks.append(stale.status_code == 409)
                        request.update(expected_version=2, idempotency_key="eval-approve-02")
                    if scenario == "restart":
                        agent.repository = SQLiteRepository(db_path)
                        with TestClient(create_app(agent, settings)) as restarted:
                            found = restarted.get(endpoint, params={"session_id": "eval-hitl"})
                        checks["recovery_after_restart"].append(
                            found.status_code == 200
                            and found.json()["action"]["status"] == "PENDING"
                        )
                    # Resume must not depend on either service, even through future refactors.
                    agent.provider = None
                    agent.tools = None
                    if scenario == "reject":
                        result = decide("reject", request)
                        checks["rejection_success"].append(
                            result.status_code == 200
                            and result.json()["result"] is None
                            and result.json()["action"]["status"] == "REJECTED"
                        )
                    elif scenario == "concurrent":

                        def concurrent(kind):
                            try:
                                return (
                                    SQLiteRepository(db_path)
                                    .decide_action(
                                        action_id,
                                        kind,
                                        ApproveActionRequest(
                                            **{**request, "idempotency_key": "concurrent-" + kind}
                                        ),
                                    )
                                    .action.status
                                )
                            except ActionConflict:
                                return "CONFLICT"

                        with ThreadPoolExecutor(max_workers=2) as pool:
                            outcomes = list(pool.map(concurrent, ("approve", "reject")))
                        record["concurrent_outcomes"] = outcomes
                        case_checks.append(outcomes.count("CONFLICT") == 1)
                    else:
                        result = decide("approve", request)
                        success = (
                            result.status_code == 200
                            and result.json()["action"]["status"] == "EXECUTED"
                            and result.json()["result"]["technical"] == proposed["technical"]
                        )
                        checks["approval_success"].append(success)
                        if scenario == "replay":
                            replay = decide("approve", request)
                            case_checks.append(replay.json() == result.json())
                    case_checks.append(len(calls) == upstream_before)
                    trace = agent.repository.get_trace(proposed["trace_id"])
                    record["trace"] = trace
                    events = agent.repository.get_action_events(action_id, "eval-hitl")
                    executions = sum(e["event"] == "ACTION_EXECUTED" for e in events)
                    with sqlite3.connect(db_path) as db:
                        publications = db.execute(
                            "SELECT count(*) FROM report_publications"
                        ).fetchone()[0]
                    duplicates += max(executions - 1, 0) + max(publications - 1, 0)
                    event_names = {e["event"] for e in events}
                    checks["trace_completeness"].append(
                        {"ACTION_PROPOSED", "ACTION_PAUSED"} <= event_names
                        and executions == publications
                        and all(
                            {
                                "actor",
                                "timestamp",
                                "version",
                                "transition",
                                "payload_sha256",
                                "idempotency_key_sha256",
                            }
                            <= e.keys()
                            for e in events
                        )
                    )
                    case_checks.append(publications == executions)
                record["pass"] = all(case_checks) and all(
                    all(v[counts_before[k] :]) for k, v in checks.items()
                )
                records.append(record)
                (output / (case["id"] + ".json")).write_text(
                    json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
                )
    metrics = {
        name: sum(values) / len(values) if values else None for name, values in checks.items()
    }
    metrics.update(duplicate_execution_count=duplicates, stale_version_rejections=stale_rejections)
    passed = (
        all(r["pass"] for r in records)
        and all(all(v) for v in checks.values())
        and duplicates == 0
        and stale_rejections == 1
    )
    report = {
        "mode": "OFFLINE_FAKE",
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "cases": len(cases),
        "passed_cases": sum(r["pass"] for r in records),
        "metrics": metrics,
        "metric_samples": {k: len(v) for k, v in checks.items()},
        "pass": passed,
    }
    (output / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report, output


if __name__ == "__main__":
    report, output = evaluate()
    print(json.dumps({"report": report, "output": str(output)}, ensure_ascii=False))
    raise SystemExit(0 if report["pass"] else 1)
