"""Bounded validation diagnostics without rejected inputs or exception messages."""

from pydantic import ValidationError

from merval_agent.domain.errors import DecisionValidationError


def validation_feedback(exc, stage):
    code = exc.code if isinstance(exc, DecisionValidationError) else "INVALID_DECISION"
    fields = {
        "action",
        "tool_name",
        "tool_args",
        "reason",
        "interpretation",
        "intent",
        "analysis_type",
        "methodology",
        "confidence",
        "missing_information",
        "query",
        "ticker",
        "range",
        "source",
    }
    issues = []
    if isinstance(exc, ValidationError):
        code = "SCHEMA_VALIDATION"
        for error in exc.errors(include_input=False, include_url=False)[:8]:
            constraint = {
                "CALL_TOOL requires tool_name": "CALL_TOOL_REQUIRES_NAME",
                "Terminal action cannot call tools": "TERMINAL_TOOL_FIELDS",
            }.get(str(error.get("ctx", {}).get("error", "")))
            issues.append(
                {
                    "type": error["type"],
                    **({"constraint": constraint} if constraint else {}),
                    "field": [
                        p if p in fields else "<field>" for p in error["loc"] if isinstance(p, str)
                    ],
                }
            )
    if str(exc) == "duplicate_tool_call":
        code = "duplicate_tool_call"
    result = {"code": code, "stage": stage, "issues": issues}
    if code == "DECISION_TEXT_BOUNDS":
        result["limits"] = {"reason": 400, "interpretation": 800, "missing_information": 10}
    return result
