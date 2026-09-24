"""Offline API acceptance; simulated market and Fake decisions, never live evidence."""

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from merval_agent.api.app import create_app
from merval_agent.bootstrap import build_agent
from merval_agent.config import Settings

ROOT = Path(__file__).resolve().parents[1]
AT = datetime(2026, 9, 16, 22, tzinfo=UTC)


def main():
    payload = json.loads((ROOT / "tests/fixtures/technical_124.json").read_text(encoding="utf-8"))
    with (
        tempfile.TemporaryDirectory() as directory,
        httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        ) as http,
    ):
        config = Settings(
            _env_file=None,
            llm_provider="fake",
            market_quote_enrichment=False,
            market_tracker_base_url="https://market-fixture.test",
            database_path=str(Path(directory) / "acceptance.sqlite3"),
        )
        agent = build_agent(config, http, clock=lambda: AT)
        with TestClient(create_app(agent=agent, settings=config)) as client:
            health = client.get("/health")
            response = client.post("/agent/run", json={"message": "Analiza técnicamente GGAL"})
            assert health.status_code == response.status_code == 200
            body = response.json()
            assert body["technical"]["assessment"]["status"] == "COMPLETE"
            assert body["technical"]["status"] == "MIXED"
            assert body["technical"]["metrics"]["sample_size"] == 124
            assert response.headers["content-type"] == "application/json; charset=utf-8"
            output = ROOT / "evals/results/technical-v3"
            output.mkdir(parents=True, exist_ok=True)
            (output / "ggal-response.json").write_text(
                json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(
                json.dumps(
                    {
                        "execution": "offline fixture + Fake, not live market or LLM",
                        "health": health.json(),
                        "response": body,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )


if __name__ == "__main__":
    main()
