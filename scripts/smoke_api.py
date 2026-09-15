"""Start real Uvicorn, check health/run locally, then stop the owned process."""

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx


def main():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="merval-smoke-") as directory:
        env = {
            **os.environ,
            "DATABASE_PATH": str(Path(directory) / "smoke.sqlite3"),
            "LLM_PROVIDER": "fake",
        }
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "merval_agent.api.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}", timeout=2, trust_env=False
            ) as http:
                deadline = time.monotonic() + 15
                while True:
                    try:
                        health = http.get("/health")
                        health.raise_for_status()
                        break
                    except httpx.HTTPError:
                        if process.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError("Uvicorn failed to start") from None
                        time.sleep(0.1)
                assert health.json()["status"] == "ok"
                response = http.post("/agent/run", json={"message": "Analizá XXXX"})
                response.raise_for_status()
                assert response.json()["status"] == "CLARIFY"
                print("Uvicorn started; GET /health=200; POST /agent/run=200 CLARIFY")
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
