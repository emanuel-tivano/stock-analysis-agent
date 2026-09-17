"""Explicit single backup model; no fallback on invalid structured decisions."""

from merval_agent.domain.errors import DecisionBudgetExhausted, ExternalServiceError


class ModelFallbackProvider:
    def __init__(self, primary, backup):
        self.primary, self.backup = primary, backup
        self.model, self.provider_name = primary.model, primary.provider_name

    def decide(self, state, tools):
        return self.decide_validated(state, tools, lambda d: None, lambda *a, **k: None)

    def decide_validated(self, state, tools, validate, emit, max_steps=12):
        if any(e.get("event") == "LLM_MODEL_FALLBACK" for e in state.trace_events):
            return self.backup.decide_validated(state, tools, validate, emit, max_steps)
        try:
            return self.primary.decide_validated(state, tools, validate, emit, max_steps)
        except DecisionBudgetExhausted:
            raise
        except ExternalServiceError as exc:
            if exc.classification not in ("RATE_LIMITED", "QUOTA_EXHAUSTED", "UNAVAILABLE"):
                raise
            emit(
                "LLM_MODEL_FALLBACK",
                provider=self.provider_name,
                requested_model=self.primary.model,
                model=self.backup.model,
                primary_error=exc.classification,
            )
            return self.backup.decide_validated(state, tools, validate, emit, max_steps)
