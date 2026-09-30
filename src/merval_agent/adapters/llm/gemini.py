"""Native Gemini generateContent adapter. No native tools or opaque parts are retained."""

import json
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import isfinite
from random import random
from time import sleep
from urllib.parse import quote

import httpx

from merval_agent.domain.models import AgentDecision

from .http_provider import HTTPDecisionProvider, ProviderResponseError


class GeminiLLMProvider(HTTPDecisionProvider):
    provider_name = "gemini"

    def __init__(self, *args, sleeper=None, random_source=None, clock=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.sleeper = sleeper
        self.random_source = random_source or random
        self.clock = clock or (lambda: datetime.now(UTC))

    def request(self, messages):
        context = json.loads(messages[1]["content"])
        objective = context.pop("user_objective")
        parts = [
            {"text": json.dumps({"user_request": objective}, ensure_ascii=False)},
            {"text": json.dumps({"agent_context": context}, ensure_ascii=False, sort_keys=True)},
        ]
        parts.extend({"text": message["content"]} for message in messages[2:])
        config = {"temperature": 0, "candidateCount": 1}
        if self.response_format != "none":
            config["responseMimeType"] = "application/json"
        if self.response_format == "json_schema":
            config["responseJsonSchema"] = AgentDecision.model_json_schema()
        return self.http.post(
            f"{self.base_url}/models/{quote(self.model, safe='')}:generateContent",
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            json={
                "systemInstruction": {"parts": [{"text": messages[0]["content"]}]},
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": config,
            },
            timeout=self.timeout,
        )

    def normalize(self, payload, metadata):
        if not isinstance(payload, dict):
            raise ProviderResponseError("INVALID_RESPONSE")
        for key in ("modelVersion", "responseId"):
            value = payload.get(key)
            if (
                isinstance(value, str)
                and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", value)
                and self.api_key not in value
            ):
                metadata[key] = value
        usage = payload.get("usageMetadata")
        if isinstance(usage, dict):
            mapping = {
                "promptTokenCount": "prompt_tokens",
                "candidatesTokenCount": "completion_tokens",
                "totalTokenCount": "total_tokens",
                "thoughtsTokenCount": "reasoning_tokens",
            }
            metadata["usage"] = {
                dest: usage[source]
                for source, dest in mapping.items()
                if type(usage.get(source)) is int and usage[source] >= 0
            }
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ProviderResponseError("NO_CANDIDATES")
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise ProviderResponseError("INVALID_CANDIDATE")
        finish = candidate.get("finishReason")
        if finish != "STOP":
            raise ProviderResponseError(
                "UNUSABLE_FINISH_REASON", retryable=finish in (None, "MAX_TOKENS", "OTHER")
            )
        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            raise ProviderResponseError("NO_TEXT")
        text = "".join(
            part["text"]
            for part in parts
            if isinstance(part, dict)
            and not part.get("thought")
            and isinstance(part.get("text"), str)
        )
        if not text.strip():
            raise ProviderResponseError("NO_TEXT")
        return text

    def error_details(self, exc):
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        retryable = True
        if status is not None:
            retryable = status == 429 or status >= 500 or status == 408
            # Use local codes, never copy provider error messages or arbitrary JSON fields.
            code = {
                400: "INVALID_ARGUMENT",
                401: "UNAUTHENTICATED",
                403: "PERMISSION_DENIED",
                429: "RESOURCE_EXHAUSTED",
                503: "UNAVAILABLE",
            }.get(status, f"HTTP_{status}")
        elif isinstance(exc, ProviderResponseError):
            code, retryable = exc.code, exc.retryable
        elif isinstance(exc, httpx.TimeoutException):
            code = "TIMEOUT"
        elif isinstance(exc, httpx.HTTPError):
            code = "TRANSPORT_ERROR"
        elif isinstance(exc, ValueError):
            code = "INVALID_DECISION"
        else:
            code = "INVALID_RESPONSE"
        classification = (
            "RATE_LIMITED"
            if status == 429
            else "CONFIGURATION_ERROR"
            if status in (400, 401, 403, 404)
            else "UNAVAILABLE"
        )
        retry_after = None
        if isinstance(exc, httpx.HTTPStatusError):
            raw = exc.response.headers.get("Retry-After")
            if raw:
                try:
                    retry_after = float(raw)
                except ValueError:
                    try:
                        retry_after = (parsedate_to_datetime(raw) - self.clock()).total_seconds()
                    except (ValueError, TypeError, OverflowError):
                        pass
                if retry_after is not None:
                    retry_after = max(0, retry_after) if isfinite(retry_after) else None
            if status == 429:
                # Only structured daily-quota identifiers justify exhaustion; 429 alone
                # cannot distinguish depleted daily quota from a temporary rate limit.
                try:
                    details = exc.response.json().get("error", {}).get("details", [])
                    for detail in details:
                        if not isinstance(detail, dict) or not str(
                            detail.get("@type", "")
                        ).endswith("google.rpc.QuotaFailure"):
                            continue
                        for violation in detail.get("violations", []):
                            quota = str(violation.get("quotaId", "")).lower()
                            if "perday" in quota or "per_day" in quota:
                                classification, retryable = "QUOTA_EXHAUSTED", False
                except (ValueError, TypeError, AttributeError):
                    pass
        return {
            "http_status": status,
            "provider_error_code": code,
            "retryable": retryable,
            "error_class": classification,
            "retry_after_seconds": retry_after,
        }

    def backoff(self, retry, emit_delay=None, retry_after_seconds=None):
        base = min(0.5 * 2**retry, 2)
        delay = min(base * (1 + self.random_source()), self.max_retry_wait_seconds)
        delay = max(delay, retry_after_seconds or 0)
        if emit_delay:
            emit_delay(delay * 1000)
        (self.sleeper or sleep)(delay)
