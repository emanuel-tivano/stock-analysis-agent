"""External LLM only; tool data are deterministic fixtures."""

import json
import os
from pathlib import Path

import httpx
import pytest

from merval_agent.agents.decisions import validate_decision
from merval_agent.bootstrap import build_provider
from merval_agent.config import Settings
from merval_agent.domain.models import AgentState, now
from merval_agent.evaluation import evaluate

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LLM_TESTS") != "1", reason="Set RUN_LLM_TESTS=1 for external LLM"
)


def test_real_llm_minimal():
    settings = Settings()
    if (
        settings.llm_provider not in ("compatible", "gemini")
        or not settings.llm_api_key.get_secret_value()
    ):
        pytest.skip("Configure a real provider")
    state = AgentState(
        user_request="Respondé únicamente con una decisión válida de aclaración: falta indicar ticker e instrumento."
    )
    events = []
    decision = None
    try:
        with httpx.Client() as http:
            provider = build_provider(settings, http)
            decision = provider.decide_validated(
                state,
                [],
                lambda d: validate_decision(d, state),
                lambda name, **fields: events.append({"event": name, **fields}),
            )
        assert decision.action in ("CLARIFY", "ABSTAIN")
    finally:
        path = Path("evals/results")
        path.mkdir(parents=True, exist_ok=True)
        record = {
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "prompt_version": settings.agent_prompt_version,
            "timestamp": now().isoformat(),
            "action": decision.action if decision else None,
            "events": events,
        }
        destination = (
            path / f"minimal_{settings.llm_provider}_{now().strftime('%Y%m%dT%H%M%S')}.json"
        )
        destination.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"provider={settings.llm_provider} action={record['action']} report={destination}")


def test_real_llm():
    settings = Settings()
    if settings.llm_provider not in ("compatible", "gemini"):
        pytest.skip("Configure a real provider")
    if not (
        settings.llm_base_url and settings.llm_model and settings.llm_api_key.get_secret_value()
    ):
        pytest.skip("LLM credentials/configuration unavailable")
    report, path = evaluate(settings)
    print(path)
    print(report["metrics"])
    assert all(row["task_success"] for row in report["cases"])
