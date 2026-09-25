"""Regression of V1 Python calculations on frozen real normalized inputs.

These fixtures validate this project's deterministic calculation and assessment.
TradingView values are deliberately outside the test contract.
"""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from merval_agent.domain.models import MarketHistory
from merval_agent.domain.technical import calculate
from merval_agent.domain.technical_assessment import assess

FIXTURES = Path(__file__).parents[1] / "fixtures" / "technical_v1"
AT = datetime(2026, 9, 25, 12, tzinfo=UTC)


def load_snapshot(name: str) -> MarketHistory:
    return MarketHistory.model_validate_json((FIXTURES / name).read_text(encoding="utf-8"))


def assert_metrics(actual, expected):
    for key, value in expected.items():
        if key == "sample_size":
            assert getattr(actual, key) == value
        else:
            assert getattr(actual, key) == pytest.approx(value, rel=1e-12, abs=1e-9)


def assert_signals(assessment, expected):
    assert {key: assessment.signals[key].signal for key in expected} == expected


def test_ggal_frozen_snapshot_calculation_and_assessment():
    history = load_snapshot("ggal_6m_20260924.json")

    assert history.ticker == "GGAL"
    assert history.resolved_variant == "ajustada"
    assert len(history.bars) == 126
    assert history.bars[0].date == date(2026, 3, 23)
    assert history.bars[-1].date == date(2026, 9, 24)
    assert history.bars[-1].close == 6395
    assert history.discarded_rows == 0
    assert history.enrichment_status == "appended"
    assert history.quote is not None and history.quote.provisional

    metrics = calculate(history.bars)
    assert_metrics(
        metrics,
        {
            "current_price": 6395.0,
            "macd_histogram": -34.77576563234351,
            "previous_macd_histogram": -26.336829985149393,
            "sma20": 6864.5,
            "sma50": 7205.6,
            "ema12": 6701.475746192057,
            "ema26": 6877.374823609121,
            "rsi14": 31.160976749318678,
            "macd": -175.8990774170643,
            "macd_signal": -141.12331178472078,
            "change_percent": -3.8345864661654128,
            "period_high": 8725.0,
            "period_low": 5950.0,
            "average_volume": 2628856.753968254,
            "sample_size": 126,
        },
    )
    assert metrics.macd_histogram == metrics.macd - metrics.macd_signal

    assessment = assess(history, metrics, AT)
    assert assessment.status == "COMPLETE"
    assert assessment.trend == "BEARISH"
    assert assessment.momentum == "BEARISH"
    assert assessment.momentum_state == "BEARISH"
    assert assessment.conclusion == "BEARISH"
    assert assessment.confidence == "MEDIUM"
    assert assessment.confirmation == "UNCONFIRMED"
    assert assessment.volume_confirmation == "CONFIRMED"
    assert assessment.volume_as_of == date(2026, 9, 23)
    assert assessment.basis.quote_in_indicators
    assert assessment.conflicts == []
    assert_signals(
        assessment,
        {
            "price_sma20": "BEARISH",
            "price_sma50": "BEARISH",
            "sma20_sma50": "BEARISH",
            "ema12_ema26": "BEARISH",
            "rsi14": "BEARISH",
            "macd_zero": "BEARISH",
            "macd_signal": "BEARISH",
            "macd_histogram": "BEARISH",
        },
    )


def test_pamp_frozen_snapshot_calculation_and_assessment():
    history = load_snapshot("pamp_6m_20260924.json")

    assert history.ticker == "PAMP"
    assert history.resolved_variant == "ajustada"
    assert len(history.bars) == 126
    assert history.bars[0].date == date(2026, 3, 23)
    assert history.bars[-1].date == date(2026, 9, 24)
    assert history.bars[-1].close == 5085
    assert history.discarded_rows == 0
    assert history.enrichment_status == "not_newer"
    assert history.quote is None

    metrics = calculate(history.bars)
    assert_metrics(
        metrics,
        {
            "current_price": 5085.0,
            "macd_histogram": -46.05821990588943,
            "previous_macd_histogram": -40.50090550670831,
            "sma20": 5358.75,
            "sma50": 5302.25,
            "ema12": 5270.959026286898,
            "ema26": 5294.235783456372,
            "rsi14": 37.38068623492972,
            "macd": -23.276757169473967,
            "macd_signal": 22.781462736415463,
            "change_percent": 3.722590515043356,
            "period_high": 5700.0,
            "period_low": 4500.0,
            "average_volume": 1081384.7698412698,
            "sample_size": 126,
        },
    )
    assert metrics.macd_histogram == metrics.macd - metrics.macd_signal

    assessment = assess(history, metrics, AT)
    assert assessment.status == "COMPLETE"
    assert assessment.trend == "MIXED"
    assert assessment.momentum == "BEARISH"
    assert assessment.momentum_state == "BEARISH"
    assert assessment.conclusion == "MIXED"
    assert assessment.confidence == "HIGH"
    assert assessment.confirmation == "UNCONFIRMED"
    assert assessment.volume_confirmation == "NOT_CONFIRMED"
    assert assessment.volume_as_of == date(2026, 9, 24)
    assert not assessment.basis.quote_in_indicators
    assert assessment.conflicts
    assert "sma20_sma50" in assessment.conflicts[0]
    assert "price_sma20" in assessment.conflicts[0]
    assert_signals(
        assessment,
        {
            "price_sma20": "BEARISH",
            "price_sma50": "BEARISH",
            "sma20_sma50": "BULLISH",
            "ema12_ema26": "BEARISH",
            "rsi14": "BEARISH",
            "macd_zero": "BEARISH",
            "macd_signal": "BEARISH",
            "macd_histogram": "BEARISH",
        },
    )
