"""Per-run operation identity and bounded, caller-requested tool retry policy."""

import hashlib
import json

import httpx

from merval_agent.domain.errors import DecisionValidationError

MAX_TOOL_ATTEMPTS = 2  # Initial attempt plus at most one explicit retry; no hidden retry.


def operation_key(call, args, state):
    relevant = {}
    # Resolution must not depend on the asset it produces.
    if call.name != "resolve_asset":
        relevant["intent"] = state.intent.model_dump()
        relevant["ticker"] = state.resolved_asset.ticker if state.resolved_asset else None
    # Recalculation is legitimate when input history changes.
    if call.name == "calculate_technical_indicators":
        relevant["history"] = (
            state.technical_data.model_dump(mode="json") if state.technical_data else None
        )
    payload = json.dumps([call.name, args, relevant], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def check_operation(key, state):
    previous = [o for o in state.observations if o.operation_key == key]
    if any(o.success for o in previous):
        raise DecisionValidationError("duplicate_tool_call")
    if previous and not previous[-1].can_retry:
        raise DecisionValidationError(
            "TOOL_RETRY_EXHAUSTED" if previous[-1].retry_budget_exhausted else "TOOL_NOT_RETRYABLE"
        )
    return len(previous) + 1


def tool_error_type(exc):
    """Inspect exception types/status only; never copy error text or response bodies."""
    current = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, httpx.HTTPStatusError):
            status = current.response.status_code
            return f"HTTP_{status}", status in (408, 429) or status >= 500
        if isinstance(current, httpx.TimeoutException):
            return "TIMEOUT", True
        if isinstance(current, httpx.TransportError):
            return "TRANSPORT_ERROR", True
        if isinstance(current, ValueError):
            return "INVALID_RESPONSE", False
        current = current.__cause__
    return "EXTERNAL_SERVICE", False
