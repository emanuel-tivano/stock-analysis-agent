"""Opt-in real provider plus live Market Tracker/Bolsar, persisted trace."""

import argparse
import json
import os
from pathlib import Path
from time import perf_counter

import httpx

from merval_agent.agents.decisions import validate_decision
from merval_agent.bootstrap import build_agent, build_provider
from merval_agent.config import Settings
from merval_agent.domain.errors import ExternalServiceError
from merval_agent.domain.models import AgentState


def smoke_provider(settings, http):
    """Provider-only smoke; no tools, persistence or raw response output."""
    state = AgentState(user_request="Necesito más información")
    events = []
    started = perf_counter()
    decision = None
    status = "OK"
    try:
        provider = build_provider(settings, http)
        decision = provider.decide_validated(
            state,
            [],
            lambda d: validate_decision(d, state),
            lambda event, **fields: events.append({"event": event, **fields}),
        )
    except ExternalServiceError:
        status = (
            "INVALID_DECISION"
            if events and events[-1]["event"] == "DECISION_VALIDATION_FAILED"
            else "PROVIDER_ERROR"
        )
    attempts = [
        e
        for e in events
        if e["event"] in ("LLM_SUCCEEDED", "LLM_FAILED", "DECISION_VALIDATION_FAILED")
    ]
    print(
        json.dumps(
            {
                "provider": settings.llm_provider,
                "model": settings.llm_model,
                "status": status,
                "decision.action": decision.action if decision else None,
                "latency_ms": (perf_counter() - started) * 1000,
                "usage": attempts[-1].get("usage") if attempts else None,
            },
            ensure_ascii=False,
        )
    )
    return 0 if decision else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider-only",
        action="store_true",
        help="Smoke only the LLM; no agent tools or external market data",
    )
    args = parser.parse_args()
    settings = Settings()
    if os.getenv("RUN_LLM_TESTS") != "1" or settings.llm_provider not in ("compatible", "gemini"):
        raise SystemExit("Set RUN_LLM_TESTS=1 and LLM_PROVIDER=compatible or gemini")
    if not (
        settings.llm_base_url and settings.llm_model and settings.llm_api_key.get_secret_value()
    ):
        raise SystemExit("Configure LLM_BASE_URL, LLM_MODEL and LLM_API_KEY")
    with httpx.Client(timeout=settings.http_timeout_seconds) as http:
        if args.provider_only:
            return smoke_provider(settings, http)
        agent = build_agent(settings, http)
        result = agent.run("Analiz\u00e1 t\u00e9cnicamente GGAL")
        trace = agent.repository.get_trace(result.trace_id)
    record = {
        "trace_id": result.trace_id,
        "model": settings.llm_model,
        "provider": settings.llm_provider,
        "prompt_version": settings.agent_prompt_version,
        "timestamp": trace["timestamp"],
        "data_mode": "external",
        "status": result.status,
        "tools": trace["tool_trace"],
        "llm_events": [
            e
            for e in trace["events"]
            if e["event"].startswith("LLM_") or e["event"] == "DECISION_VALIDATION_FAILED"
        ],
        "analysis": result.model_dump(mode="json"),
    }
    output = Path("evals/results")
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"live_{result.trace_id}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"status={result.status} trace_id={result.trace_id} report={path}")
    return 1 if result.status == "ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
