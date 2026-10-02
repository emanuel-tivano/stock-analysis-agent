import pytest
from pydantic import TypeAdapter, ValidationError

from merval_agent.domain.errors import DecisionValidationError
from merval_agent.domain.models import (
    AgentDecision,
    AgentState,
    Bar,
    HistoryRange,
    Ticker,
    ToolCall,
    ToolResult,
)
from merval_agent.tools.assets import resolve_asset
from merval_agent.tools.registry import ResolveArgs, build_registry


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


@pytest.mark.parametrize("ticker", ["GGAL", "YPFD", "PAMP"])
def test_resolve_known_local_assets(ticker):
    resolution = resolve_asset(ticker)
    assert resolution.status == "RESOLVED"
    assert resolution.ticker == ticker
    assert resolution.market == "bCBA"


def test_resolve_ambiguous_missing_foreign_and_invalid_assets():
    assert resolve_asset("Galicia").status == "AMBIGUOUS"
    assert resolve_asset("PPSA").status == "NOT_FOUND"
    assert resolve_asset("empresa inexistente").status == "NOT_FOUND"
    foreign = resolve_asset("GGAL ADR", symbol="GGAL", market="NYSE")
    assert foreign.status == "UNSUPPORTED"
    assert foreign.eligibility_reason == "FOREIGN_MARKET"
    with pytest.raises(ValidationError):
        ResolveArgs.model_validate({"symbol": "$$$"})


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


def test_resolve_tool_schema_only_exposes_symbol_and_market():
    schema = ResolveArgs.model_json_schema()
    assert set(schema["properties"]) == {"symbol", "market"}
    for removed in ({"query": "GGAL"}, {"company_name": "Galicia"}):
        with pytest.raises(ValidationError):
            ResolveArgs.model_validate(removed)


def test_resolve_operation_identity_preserves_duplicates_and_retries():
    registry = build_registry(None)
    state = AgentState(user_request="Analizá GGAL")
    proposed = ToolCall(name="resolve_asset", arguments={"symbol": "GGAL"})
    equivalent = ToolCall(
        name="resolve_asset", arguments={"market": None, "symbol": "GGAL"}
    )

    _, first_key, first_attempt = registry.prepare(proposed, state)
    _, equivalent_key, equivalent_attempt = registry.prepare(equivalent, state)
    assert first_key == equivalent_key
    assert first_attempt == equivalent_attempt == 1

    state.observations = [
        ToolResult(
            tool_name="resolve_asset",
            success=False,
            operation_key=first_key,
            attempts=1,
            can_retry=True,
        )
    ]
    assert registry.prepare(equivalent, state)[2] == 2

    state.observations = [
        ToolResult(tool_name="resolve_asset", success=True, operation_key=first_key)
    ]
    with pytest.raises(DecisionValidationError, match="duplicate_tool_call"):
        registry.prepare(equivalent, state)


def test_resolve_uses_original_request_as_authority():
    registry = build_registry(None)
    state = AgentState(user_request="Analizá GGAL")
    conflicting = ToolCall(
        name="resolve_asset", arguments={"symbol": "PAMP", "market": "bCBA"}
    )
    with pytest.raises(DecisionValidationError, match="ASSET_PROPOSAL_CONFLICT"):
        registry.prepare(conflicting, state)
