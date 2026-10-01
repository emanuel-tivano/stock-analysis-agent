"""Opt-in PostgreSQL contract test for the Vercel persistence boundary."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from merval_agent.api.app import create_app
from merval_agent.config import Settings
from merval_agent.memory.postgres import PostgresRepository


class LivePostgresSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    test_database_url: SecretStr = SecretStr("")


@pytest.mark.live
def test_postgres_preserves_hitl_across_repository_restarts(make_agent):
    database_url = os.getenv("TEST_DATABASE_URL", "").strip()
    if not database_url:
        database_url = LivePostgresSettings().test_database_url.get_secret_value().strip()
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required in the process or local .env")

    agent, _ = make_agent()
    agent.repository = PostgresRepository(database_url)
    session_id = "postgres-" + uuid4().hex
    settings = Settings(_env_file=None, database_url=database_url)

    with TestClient(create_app(agent=agent, settings=settings)) as client:
        paused = client.post(
            "/agent/run",
            json={
                "message": "Prepará un informe técnico de GGAL para revisión.",
                "session_id": session_id,
            },
        ).json()
        assert paused["status"] == "PAUSED"
        action = paused["pending_action"]

        # Simulate a new serverless instance before the human decision.
        agent.repository = PostgresRepository(database_url)
        approved = client.post(
            f"/agent/actions/{action['action_id']}/approve",
            json={
                "session_id": session_id,
                "expected_version": action["version"],
                "idempotency_key": "approve-" + uuid4().hex,
            },
        )
        assert approved.status_code == 200
        assert approved.json()["result"]["status"] == "ANSWER"

        fetched = client.get(
            f"/agent/actions/{action['action_id']}", params={"session_id": session_id}
        )
        assert fetched.json() == approved.json()

    rate_limit_key = "live-rate-limit-" + uuid4().hex
    rate_limit_repository = PostgresRepository(database_url)

    def consume(_):
        return rate_limit_repository.consume_rate_limit(
            rate_limit_key, "concurrency", 1_800_000_000, 3, 1_800_000_000
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(consume, range(12))) == 3
