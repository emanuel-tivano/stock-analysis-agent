"""Public generation metadata derived from sanitized per-run trace events."""

from merval_agent.domain.models import Generation


def describe_generation(events: list[dict], status: str, degraded: bool) -> Generation:
    attempts = [
        e
        for e in events
        if e["event"] in ("LLM_SUCCEEDED", "LLM_FAILED", "DECISION_VALIDATION_FAILED")
    ]
    if not attempts:
        return Generation(mode="FAILED" if status == "ERROR" else "SIMULATED")
    last = attempts[-1]
    successes = [e for e in attempts if e["event"] == "LLM_SUCCEEDED"]
    model_version = (
        successes[-1].get("modelVersion")
        if successes and last["event"] == "LLM_SUCCEEDED"
        else None
    )
    outcome = (
        "SUCCEEDED"
        if last["event"] == "LLM_SUCCEEDED"
        else (
            "INVALID_OUTPUT"
            if last["event"] == "DECISION_VALIDATION_FAILED"
            else last.get("error_class", "UNAVAILABLE")
        )
    )
    used_fallback = any(e["event"] == "LLM_MODEL_FALLBACK" for e in events)
    warnings = []
    if degraded:
        warnings.append(
            "El LLM no pudo finalizar; se entrega únicamente el análisis técnico ya calculado por Python."
        )
    if used_fallback:
        warnings.append("Falló el modelo principal; se intentó el modelo alternativo autorizado.")
    return Generation(
        mode="DETERMINISTIC_FALLBACK"
        if degraded and status == "ANSWER"
        else "FAILED"
        if status == "ERROR"
        else "LLM_ORCHESTRATED",
        llm_status=outcome,
        provider=last.get("provider"),
        requested_model=attempts[0].get("model"),
        model=last.get("model"),
        model_version=model_version,
        attempts=len(attempts),
        retry_after_seconds=last.get("retry_after_seconds") if outcome != "SUCCEEDED" else None,
        model_fallback_used=used_fallback,
        warnings=warnings,
    )
