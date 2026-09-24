"""Real Uvicorn + SQLite restart and decision smoke. All market/LLM inputs are offline."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx


def start(port, database):
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "demo_hitl:create_demo",
            "--factory",
            "--app-dir",
            str(Path(__file__).resolve().parent),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env={**os.environ, "HITL_DEMO_DATABASE": str(database), "LLM_PROVIDER": "fake"},
        cwd=str(Path(database).parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def wait_ready(http, process):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and process.poll() is None:
        try:
            if http.get("/health").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise RuntimeError("Demo server unavailable")


def stop(process):
    if process.poll() is None:
        process.terminate()
    process.wait(timeout=10)


def main():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="hitl-smoke-") as directory:
        database = Path(directory) / "hitl.sqlite3"
        process = start(port, database)
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}", timeout=10, trust_env=False
            ) as http:
                wait_ready(http, process)
                paused = http.post(
                    "/agent/run",
                    json={
                        "message": "Prepará un informe técnico de GGAL para revisión.",
                        "session_id": "smoke-hitl",
                    },
                )
                paused.raise_for_status()
                paused = paused.json()
                assert paused["status"] == "PAUSED", paused
                endpoint = "/agent/actions/" + paused["pending_action"]["action_id"]
                decision = {
                    "session_id": "smoke-hitl",
                    "expected_version": 1,
                    "idempotency_key": "modify-smoke",
                }
                modified = http.post(
                    endpoint + "/modify",
                    json={
                        **decision,
                        "changes": {"focus": "momentum", "review_note": "Revisión UTF-8"},
                    },
                )
                modified.raise_for_status()
                assert modified.json()["action"]["status"] == "MODIFIED"
                stop(process)
                process = start(port, database)
                wait_ready(http, process)
                restored = http.get(endpoint, params={"session_id": "smoke-hitl"})
                assert restored.json()["action"]["version"] == 2
                decision.update(expected_version=2, idempotency_key="approve-smoke")
                approved = http.post(endpoint + "/approve", json=decision)
                approved.raise_for_status()
                replay = http.post(endpoint + "/approve", json=decision)
                assert replay.json() == approved.json()
                assert approved.json()["result"]["technical"] == paused["technical"]
                trace = http.get(endpoint + "/events", params={"session_id": "smoke-hitl"}).json()
                assert sum(e["event"] == "ACTION_EXECUTED" for e in trace) == 1
                assert [e["event"] for e in trace] == [
                    "ACTION_PROPOSED",
                    "ACTION_PAUSED",
                    "ACTION_MODIFIED",
                    "ACTION_APPROVED",
                    "ACTION_EXECUTED",
                ]
                rejected = http.post(
                    "/agent/run",
                    json={
                        "message": "Prepará un informe técnico de PAMP",
                        "session_id": "smoke-hitl",
                    },
                ).json()
                rejection = http.post(
                    "/agent/actions/" + rejected["pending_action"]["action_id"] + "/reject",
                    json={**decision, "expected_version": 1, "idempotency_key": "reject-smoke"},
                )
                assert rejection.json()["action"]["status"] == "REJECTED"
                assert rejection.json()["result"] is None
                print(
                    json.dumps(
                        {
                            "mode": "OFFLINE_FAKE",
                            "paused": True,
                            "modified": True,
                            "restarted": True,
                            "approved": True,
                            "replayed": True,
                            "rejected": True,
                            "executions": 1,
                            "duplicate_execution_count": 0,
                        }
                    )
                )
        finally:
            stop(process)


if __name__ == "__main__":
    main()
