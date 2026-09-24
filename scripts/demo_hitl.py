"""Offline demo factory: Fake decisions + synthetic market; real API and SQLite HITL.

uvicorn demo_hitl:create_demo --factory --app-dir scripts --host 127.0.0.1 --port 8010
Never reads .env or calls external services.
"""

import os
from pathlib import Path

import httpx
from smoke_api import market_payload

from merval_agent.api.app import create_app
from merval_agent.bootstrap import build_agent
from merval_agent.config import Settings


def create_demo():
    def handle(request):
        if request.url.path.endswith("/history"):
            ticker = request.url.path.split("/")[-2]
            return httpx.Response(
                200, json=market_payload(ticker, request.url.params.get("range", "6M"))
            )
        return httpx.Response(503, json={"ok": False})

    settings = Settings(
        _env_file=None,
        llm_provider="fake",
        llm_api_key="",
        llm_model="",
        market_tracker_base_url="https://synthetic-market.test",
        bolsar_base_url="https://synthetic-documents.test",
        database_path=os.environ.get("HITL_DEMO_DATABASE", str(Path("data") / "hitl-demo.sqlite3")),
    )
    transport = httpx.Client(transport=httpx.MockTransport(handle))
    agent = build_agent(settings, transport)
    return create_app(agent, settings)
