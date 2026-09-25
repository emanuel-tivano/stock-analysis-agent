import pytest
from pydantic import TypeAdapter, ValidationError

from merval_agent.domain.models import AgentDecision, Bar, HistoryRange, Ticker
from merval_agent.tools.assets import resolve_asset


def test_ticker_validation():
    for value in ("GGAL", "TECO2", "TGNO4", "TGSU2", "A3"):
        assert TypeAdapter(Ticker).validate_python(f" {value.lower()} ") == value
    for value in (
        "../GGAL",
        "GGAL?x=1",
        "123",
        "TOOLONG",
        "A",
        "A33",
        "T3CO2",
        "TECO22",
    ):
        with pytest.raises(ValidationError):
            TypeAdapter(Ticker).validate_python(value)
    assert resolve_asset("GGAL").company_type == "FINANCIAL"
    assert resolve_asset("Galicia").ticker is None
    assert resolve_asset("XXXX").ticker is None
    assert resolve_asset("GGAL y PAMP").ticker is None


def test_range():
    for value in ("1W", "1M", "3M", "6M", "1Y"):
        assert TypeAdapter(HistoryRange).validate_python(value) == value
    with pytest.raises(ValidationError):
        TypeAdapter(HistoryRange).validate_python("5Y")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"action": "CALL_TOOL"},
        {"action": "ABSTAIN", "tool_name": "x"},
        {"action": "BUY"},
        {"action": "CLARIFY", "confidence": 2},
    ],
)
def test_invalid_decision(kwargs):
    with pytest.raises(ValidationError):
        AgentDecision.model_validate({"reason": "reason", "confidence": 1, **kwargs})


def test_invalid_bar():
    with pytest.raises(ValidationError):
        Bar(date="2026-01-01", open=10, high=5, low=4, close=7, volume=10)
