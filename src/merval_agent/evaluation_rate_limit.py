"""Sequential request pacing for the real evaluator's dedicated HTTP client."""

import math
from time import monotonic, sleep


class SequentialLLMRateLimiter:
    """HTTP request hook shared across all steps, retries and cases in one eval.

    Measures start-to-start intervals with a monotonic clock. This is deliberately
    sequential: it does not coordinate concurrent callers or other processes.
    """

    def __init__(self, min_interval_seconds):
        if not math.isfinite(min_interval_seconds) or min_interval_seconds < 0:
            raise ValueError("Interval must be finite and nonnegative")
        self.min_interval_seconds = min_interval_seconds
        self._last_request_started = None

    def __call__(self, request):
        if not self.min_interval_seconds:
            return
        if self._last_request_started is not None:
            remaining = self.min_interval_seconds - (monotonic() - self._last_request_started)
            while remaining > 0:
                sleep(remaining)
                remaining = self.min_interval_seconds - (monotonic() - self._last_request_started)
        self._last_request_started = monotonic()
