from datetime import UTC, datetime, timedelta

import pytest

from merval_agent.agents.intent import explicit_analysis_type
from merval_agent.domain.models import Bar, MarketHistory
from merval_agent.domain.technical import calculate
from merval_agent.domain.technical_assessment import assess

AT = datetime(2026, 9, 16, 22, tzinfo=UTC)


def history():
    return MarketHistory(
        ticker="GGAL",
        range="6M",
        source="fixture://v1",
        mode="live",
        fetched_at=AT,
        bars=[
            Bar(
                date=AT.date() - timedelta(days=59 - i),
                open=100 + i,
                close=100 + i,
                high=101 + i,
                low=99 + i,
                volume=100,
            )
            for i in range(60)
        ],
    )


@pytest.mark.parametrize(
    "message",
    [
        "¿GGAL está sobrecomprada?",
        "Revisa el momentum de BMA",
        "¿Cómo está la tendencia de Galicia?",
        "RSI de GGAL",
    ],
)
def test_technical_paraphrases(message):
    assert explicit_analysis_type(message) == "technical"


def test_rsi_and_macd_territory_conflict_is_mixed():
    h = history()
    m = calculate(h.bars)
    m.rsi14 = 40  # Isolate the aggregation rule, not the price calculation.
    a = assess(h, m, AT)
    assert a.trend == "BULLISH"
    assert a.conclusion == "MIXED"
    assert a.conflicts


def test_volume_confirms_observed_price_direction():
    h = history()
    h.bars[-1].volume = 200
    a = assess(h, calculate(h.bars), AT)
    assert a.signals["volume"].signal == "BULLISH"
    assert "20" in a.signals["volume"].explanation


def test_future_receipt_same_day_is_invalid():
    h = history()
    h.fetched_at = AT + timedelta(minutes=1)
    assert assess(h, calculate(h.bars), AT).status == "INVALID_DATA"


def test_known_recent_volume_can_be_used_without_inventing_older_volume():
    h = history()
    h.bars[0].volume = None
    h.bars[-1].volume = 200
    metrics = calculate(h.bars)
    a = assess(h, metrics, AT)
    assert metrics.average_volume is None
    assert a.signals["volume"].signal == "BULLISH"
    assert "no se confirma la señal" not in " ".join(a.warnings)


def test_provider_cannot_override_explicit_technical_intent():
    from merval_agent.agents.decisions import validate_decision
    from merval_agent.domain.errors import DecisionValidationError
    from merval_agent.domain.models import AgentDecision, AgentState, UserIntent

    state = AgentState(
        user_request="Revisa el momentum de BMA", intent=UserIntent(analysis_type="technical")
    )
    decision = AgentDecision(
        action="CALL_TOOL",
        tool_name="resolve_asset",
        tool_args={"query": state.user_request},
        reason="route",
        confidence=1,
        intent=UserIntent(analysis_type="full"),
    )
    with pytest.raises(DecisionValidationError):
        validate_decision(decision, state)
