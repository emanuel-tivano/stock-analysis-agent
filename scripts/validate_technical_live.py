"""Explicit opt-in acceptance with configured Gemini and real market sources.

Saves complete responses and normalized market snapshots, never keys or LLM payloads.
"""

import argparse
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from urllib.parse import quote

import httpx

from merval_agent.bootstrap import build_agent
from merval_agent.config import Settings
from merval_agent.domain.technical import calculate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", action="append", required=True)
    parser.add_argument("--check-model", action="append", default=[])
    args = parser.parse_args()
    if os.getenv("RUN_LLM_TESTS") != "1" or os.getenv("RUN_LIVE_TESTS") != "1":
        parser.error("Set RUN_LLM_TESTS=1 and RUN_LIVE_TESTS=1 explicitly")
    settings = Settings()
    if settings.llm_provider != "gemini" or not settings.llm_api_key.get_secret_value():
        parser.error("Configured Gemini credentials are required")
    output = Path("evals/results/technical-v4") / datetime.now(UTC).strftime("live-%Y%m%dT%H%M%SZ")
    output.mkdir(parents=True, exist_ok=True)
    # Independent acceptance database; existing sessions are not modified.
    settings = settings.model_copy(update={"database_path": str(output / "traces.sqlite3")})
    logging.getLogger("httpx").setLevel(logging.WARNING)
    availability = []
    with httpx.Client(timeout=settings.http_timeout_seconds) as http:
        for model in dict.fromkeys([settings.llm_model, *args.check_model]):
            try:
                response = http.get(
                    f"{settings.llm_base_url.rstrip('/')}/models/{quote(model, safe='')}",
                    headers={"x-goog-api-key": settings.llm_api_key.get_secret_value()},
                )
                availability.append(
                    {
                        "model": model,
                        "http_status": response.status_code,
                        "supports_generate_content": response.status_code == 200
                        and "generateContent"
                        in response.json().get("supportedGenerationMethods", []),
                    }
                )
            except httpx.HTTPError as exc:
                availability.append({"model": model, "transport_error": type(exc).__name__})
                (output / "availability.json").write_text(
                    json.dumps(availability, indent=2), encoding="utf-8"
                )
                print(json.dumps({"availability": availability, "output": str(output)}))
                return 2
        (output / "availability.json").write_text(
            json.dumps(availability, indent=2), encoding="utf-8"
        )
        print(json.dumps({"availability": availability}), flush=True)
        if not availability[0]["supports_generate_content"]:
            return 2
        for ticker in args.ticker:
            agent = build_agent(settings, http)
            repository = agent.repository
            captured = []

            class Capture:
                def save(self, state, result):
                    captured.append(state.model_copy(deep=True))
                    repository.save(state, result)

            agent.repository = Capture()
            started = perf_counter()
            result = agent.run(f"Analiza técnicamente {ticker}")
            elapsed = (perf_counter() - started) * 1000
            state = captured[-1] if captured else None
            snapshot = state.technical_data if state else None
            verified = (
                result.technical.metrics == calculate(snapshot.bars)
                if snapshot and result.technical.metrics
                else None
            )
            record = {
                "data_mode": "real_market_and_gemini",
                "latency_ms": elapsed,
                "metrics_match_python": verified,
                "analysis": result.model_dump(mode="json"),
                "snapshot": snapshot.model_dump(mode="json") if snapshot else None,
                "trace": repository.get_trace(result.trace_id),
            }
            (output / f"{result.trace_id}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                json.dumps(
                    {
                        "requested_ticker": ticker,
                        "status": result.status,
                        "technical_status": result.technical.status,
                        "assessment_status": result.technical.assessment.status
                        if result.technical.assessment
                        else None,
                        "generation": result.generation.model_dump(),
                        "latency_ms": elapsed,
                        "metrics_match_python": verified,
                        "trace_id": result.trace_id,
                        "output": str(output),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
