"""Opt-in HTTP adapter; bounded retries include schema and business validation."""

import hashlib
import json
from time import perf_counter

import httpx

from merval_agent.agents.validation_feedback import validation_feedback
from merval_agent.domain.errors import (
    DecisionBudgetExhausted,
    DecisionValidationError,
    ExternalServiceError,
)
from merval_agent.domain.models import AgentDecision, AgentState

from .context import AGENT_PROMPT_VERSION, build_agent_context, get_system_instructions


class ProviderResponseError(Exception):
    def __init__(self, code, retryable=True):
        self.code, self.retryable = code, retryable
        super().__init__(code)


class HTTPDecisionProvider:
    provider_name = "compatible"

    def request(self, messages):
        raise NotImplementedError

    def normalize(self, payload, metadata):
        raise NotImplementedError

    def error_details(self, exc):
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        if status is not None:
            return {
                "http_status": status,
                "provider_error_code": f"HTTP_{status}",
                "retryable": status in (408, 429) or status >= 500,
            }
        code = (
            exc.code
            if isinstance(exc, ProviderResponseError)
            else "TIMEOUT"
            if isinstance(exc, httpx.TimeoutException)
            else "TRANSPORT_ERROR"
            if isinstance(exc, httpx.HTTPError)
            else "INVALID_RESPONSE"
        )
        return {
            "http_status": None,
            "provider_error_code": code,
            "retryable": getattr(exc, "retryable", True),
        }

    def backoff(self, retry, emit_delay=None, retry_after_seconds=None):
        if emit_delay:
            emit_delay(0)

    def __init__(
        self,
        http: httpx.Client,
        base_url: str,
        model: str,
        api_key: str,
        *,
        timeout: float = 20,
        max_retries: int = 1,
        prompt_version: str = AGENT_PROMPT_VERSION,
        response_format: str = "json_object",
        max_retry_wait_seconds: float = 30,
    ):
        if not base_url or not model or not api_key:
            raise ValueError("Configure LLM_BASE_URL, LLM_MODEL and LLM_API_KEY")
        if not 0 <= max_retries <= 2:
            raise ValueError("max_retries must be between 0 and 2")
        if response_format not in ("json_object", "json_schema", "none"):
            raise ValueError("Unsupported response format")
        self.http, self.base_url, self.model, self.api_key = (
            http,
            base_url.rstrip("/"),
            model,
            api_key,
        )
        self.timeout, self.max_retries = timeout, max_retries
        self.max_retry_wait_seconds = max_retry_wait_seconds
        self.prompt_version, self.response_format = prompt_version, response_format
        get_system_instructions(prompt_version)  # Reject mislabeled experiments before HTTP.

    def decide(self, state: AgentState, tools: list[dict]) -> AgentDecision:
        return self.decide_validated(state, tools, lambda d: None, lambda *a, **k: None)

    def decide_validated(self, state, tools, validate, emit, max_steps=12):
        system = (
            get_system_instructions(self.prompt_version)
            + "\nSchema:\n"
            + json.dumps(AgentDecision.model_json_schema())
        )
        content = json.dumps(
            build_agent_context(state, tools, max_steps), ensure_ascii=False, sort_keys=True
        )
        messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        for retry in range(self.max_retries + 1):
            serialized = json.dumps(messages, ensure_ascii=False).encode("utf-8")
            metadata = dict(
                provider=self.provider_name,
                model=self.model,
                prompt_version=self.prompt_version,
                retry_number=retry,
                prompt_hash=hashlib.sha256(serialized).hexdigest(),
                prompt_bytes=len(serialized),
            )
            emit("LLM_STARTED", **metadata)
            started = perf_counter()
            response_metadata = {"usage": None}
            proposed_tool = None
            proposed_source = None
            response = None
            stage = "transport"
            try:
                response = self.request(messages)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ProviderResponseError("INVALID_RESPONSE")
                raw = self.normalize(payload, response_metadata)
                stage = "decision_schema"
                if not isinstance(raw, str) or len(raw) > 32000:
                    raise DecisionValidationError("DECISION_CONTENT_BOUNDS")
                decision = AgentDecision.model_validate_json(raw)
                if (
                    len(decision.reason) > 400
                    or len(decision.interpretation) > 800
                    or len(decision.missing_information) > 10
                ):
                    raise DecisionValidationError("DECISION_TEXT_BOUNDS")
                if decision.tool_name in {t["name"] for t in tools}:
                    proposed_tool = decision.tool_name
                if decision.tool_args.get("source") in ("murphy", "graham"):
                    proposed_source = decision.tool_args["source"]
                stage = "business_or_tool_arguments"
                validate(decision)
            except (
                httpx.HTTPError,
                KeyError,
                IndexError,
                TypeError,
                ValueError,
                ProviderResponseError,
            ) as exc:
                invalid = isinstance(exc, ValueError) and stage != "transport"
                code = "INVALID_DECISION" if invalid else "LLM_FAILURE"
                error_metadata = self.error_details(exc)
                error_metadata["error_class"] = (
                    "INVALID_OUTPUT"
                    if invalid
                    else error_metadata.get("error_class", "UNAVAILABLE")
                )
                if "http_status" in error_metadata and response is not None:
                    error_metadata["http_status"] = response.status_code
                duplicate = str(exc) == "duplicate_tool_call"
                feedback = validation_feedback(exc, stage) if invalid else None
                emit(
                    "DECISION_VALIDATION_FAILED" if invalid else "LLM_FAILED",
                    **metadata,
                    latency_ms=(perf_counter() - started) * 1000,
                    **response_metadata,
                    validation_outcome=code,
                    tool_name=proposed_tool,
                    source=proposed_source,
                    duplicate_tool_call=duplicate,
                    validation_feedback=feedback,
                    **error_metadata,
                )
                retry_after = error_metadata.get("retry_after_seconds")
                deferred = retry_after is not None and retry_after > self.max_retry_wait_seconds
                if deferred:
                    emit(
                        "LLM_RETRY_DEFERRED",
                        **metadata,
                        retry_after_seconds=retry_after,
                        reason="RETRY_AFTER_EXCEEDS_WAIT_BUDGET",
                    )
                if (
                    retry == self.max_retries
                    or not error_metadata.get("retryable", True)
                    or deferred
                ):
                    if invalid:
                        raise DecisionBudgetExhausted("Decision repair budget exhausted") from None
                    raise ExternalServiceError(
                        "LLM retry budget exhausted",
                        retryable=error_metadata.get("retryable", False),
                        classification=error_metadata["error_class"],
                        http_status=error_metadata.get("http_status"),
                    ) from None
                self.backoff(
                    retry,
                    lambda delay_ms: emit(
                        "LLM_RETRY_DELAY",
                        **metadata,
                        retry_delay_ms=delay_ms,
                        next_retry_number=retry + 1,
                        retry_kind="decision_repair" if invalid else "provider_transport",
                    ),
                    retry_after_seconds=retry_after,
                )
                messages = messages[:2] + [
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "previous_attempt_failed": feedback or {"code": code},
                                "current_intent": state.intent.model_dump(),
                                "intent_locked": bool(state.tool_calls),
                                "repair": "Return one valid decision using the supplied schema. "
                                "Keep locked intent unchanged (or omit intent). Reuse existing data; "
                                "do not repeat completed or exhausted operations. Choose a different "
                                "permitted action, or a justified terminal decision.",
                            }
                        ),
                    }
                ]
            else:
                emit(
                    "LLM_SUCCEEDED",
                    **metadata,
                    latency_ms=(perf_counter() - started) * 1000,
                    **response_metadata,
                    validation_outcome="VALID",
                    http_status=response.status_code,
                    error_class=None,
                )
                return decision
        raise ExternalServiceError("LLM retry budget exhausted")
