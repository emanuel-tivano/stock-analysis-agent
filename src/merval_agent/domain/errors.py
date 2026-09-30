class ExternalServiceError(Exception):
    """External service unavailable or response contract violated."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        classification: str = "FAILED",
        http_status: int | None = None,
    ):
        self.retryable = retryable
        self.classification = classification
        self.http_status = http_status
        super().__init__(message)


class DecisionBudgetExhausted(ExternalServiceError):
    """The model replied, but no valid decision remained within its repair budget."""


class DecisionValidationError(ValueError):
    """Local, safe-to-log validation code; never contains model/provider text."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)
