"""Offline 429 acceptance using the real Gemini adapter with mocked HTTP only."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from merval_agent.api.app import create_app
from merval_agent.bootstrap import build_agent
from merval_agent.config import Settings


def main():
    output = Path("evals/results/technical-v4/mock-429")
    output.mkdir(parents=True, exist_ok=True)
    payload = json.loads(Path("tests/fixtures/technical_124.json").read_text(encoding="utf-8"))
    steps = [
        ("resolve_asset", {"query": "GGAL"}),
        ("get_market_history", {"ticker": "GGAL", "range": "6M"}),
        ("calculate_technical_indicators", {"ticker": "GGAL"}),
    ]

    def handler(request):
        if request.url.host == "market-fixture.test":
            return httpx.Response(200, json=payload)
        if not steps:
            return httpx.Response(
                429, headers={"Retry-After": "2"}, json={"error": {"status": "RESOURCE_EXHAUSTED"}}
            )
        name, args = steps.pop(0)
        decision = {
            "action": "CALL_TOOL",
            "tool_name": name,
            "tool_args": args,
            "reason": "fixture operation",
            "confidence": 1,
            "intent": {"analysis_type": "technical"},
        }
        return httpx.Response(
            200,
            json={
                "modelVersion": "mock-gemini",
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(decision)}]}}
                ],
            },
        )

    config = Settings(
        _env_file=None,
        llm_provider="gemini",
        llm_base_url="https://gemini-fixture.test",
        llm_model="mock-gemini",
        llm_api_key="test-only",
        llm_max_retries=1,
        market_tracker_base_url="https://market-fixture.test",
        market_quote_enrichment=False,
        database_path=str(output / "traces.sqlite3"),
    )
    fixed = datetime(2026, 9, 16, 22, tzinfo=UTC)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        agent = build_agent(config, http, clock=lambda: fixed)
        agent.provider.sleeper = lambda _: None
        agent.provider.random_source = lambda: 0.5
        with TestClient(create_app(agent=agent, settings=config)) as client:
            response = client.post("/agent/run", json={"message": "Analiza técnicamente GGAL"})
        body = response.json()
        assert body["status"] == "ANSWER"
        assert body["generation"]["mode"] == "DETERMINISTIC_FALLBACK"
        assert body["generation"]["llm_status"] == "RATE_LIMITED"
        trace = agent.repository.get_trace(body["trace_id"])
        record = {
            "execution": "MOCK: no Gemini or market network; clock and sleep injected",
            "http_status": response.status_code,
            "analysis": body,
            "trace": trace,
        }
        path = output / "response.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {"status": body["status"], "generation": body["generation"], "path": str(path)},
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
