"""Small, storage-backed rate limiter for the public API boundary."""

from __future__ import annotations

import hashlib
import ipaddress
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request

WINDOW_SECONDS = 60
RATE_LIMIT_MESSAGE = "Demasiadas solicitudes. Intentá nuevamente en unos segundos."


def _normalized_ip(value: str | None) -> str | None:
    if not value or len(value) > 64 or "," in value:
        return None
    try:
        return ipaddress.ip_address(value.strip()).compressed
    except ValueError:
        return None


def _normalized_peer(value: str | None) -> str:
    if not value:
        return "unknown"
    normalized = _normalized_ip(value)
    if normalized:
        return normalized
    value = value.strip().casefold()
    if 0 < len(value) <= 255 and all(char.isalnum() or char in ".-_" for char in value):
        return value
    return "unknown"


def client_key(request: Request, *, trust_vercel_headers: bool) -> str:
    """Return a stable pseudonymous key without retaining the complete client IP."""
    address = None
    if trust_vercel_headers:
        address = _normalized_ip(request.headers.get("x-vercel-forwarded-for"))
    if address is None:
        address = _normalized_peer(request.client.host if request.client else None)
    return hashlib.sha256(f"merval-rate-limit-v1:{address}".encode()).hexdigest()


def protected_bucket(method: str, path: str) -> str | None:
    """Map only cost-bearing public POST routes to independent quota buckets."""
    if method != "POST":
        return None
    if path == "/chat":
        return "chat"
    if path == "/agent/run":
        return "agent_run"
    parts = path.split("/")
    if (
        len(parts) == 5
        and parts[1:3] == ["agent", "actions"]
        and parts[4] in {"approve", "modify", "reject"}
    ):
        return "hitl"
    return None


class InMemoryRateLimitStore:
    """Process-local fallback for injected/fake repositories used by tests."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[tuple[str, str, int], int] = {}

    def consume_rate_limit(
        self,
        client: str,
        bucket: str,
        window_start: int,
        limit: int,
        expires_before: int,
    ) -> bool:
        key = (client, bucket, window_start)
        with self._lock:
            self._counts = {
                stored_key: count
                for stored_key, count in self._counts.items()
                if stored_key[2] >= expires_before
            }
            count = self._counts.get(key, 0)
            if count >= limit:
                return False
            self._counts[key] = count + 1
            return True


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after: int


class RateLimiter:
    def __init__(
        self,
        repository,
        *,
        enabled: bool,
        limits: dict[str, int],
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.enabled = enabled
        self.limits = limits
        self.clock = clock or time.time
        self.store = (
            repository
            if callable(getattr(repository, "consume_rate_limit", None))
            else InMemoryRateLimitStore()
        )

    def check(self, bucket: str, client: str) -> RateLimitResult:
        if not self.enabled:
            return RateLimitResult(allowed=True, retry_after=0)
        current = float(self.clock())
        window_start = math.floor(current / WINDOW_SECONDS) * WINDOW_SECONDS
        allowed = self.store.consume_rate_limit(
            client,
            bucket,
            window_start,
            self.limits[bucket],
            window_start,
        )
        retry_after = max(1, math.ceil(window_start + WINDOW_SECONDS - current))
        return RateLimitResult(allowed=allowed, retry_after=retry_after)
