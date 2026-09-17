from datetime import UTC, datetime, timedelta

import pytest

from merval_agent.agents.intent import explicit_analysis_type
from merval_agent.domain.models import Bar, MarketHistory
from merval_agent.domain.technical import calculate
from merval_agent.domain.technical_assessment import assess

AT = datetime(2026, 9, 16, 22, tzinfo=UTC)


def history():
    return MarketHistory(
        ticker="GGAL", range="6M", source="fixture://v1", mode="live", fetched_at=AT,
        bars=[Bar(date=AT.date() - timedelta(days=59-i), open=100+i,
                  close=100+i, high=101+i, low=99+i, volume=100) for i in range(60)],
    )


@pytest.mark.parametrize("message", ["¿GGAL está sobrecomprada?", "Revisa el momentum de BMA",
                                    "¿Cómo está la tendencia de Galicia?", "RSI de GGAL"])
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
