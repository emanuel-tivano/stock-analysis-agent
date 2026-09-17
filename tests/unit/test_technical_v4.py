from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from merval_agent.adapters.market_tracker import ArgentinaMarketTrackerClient, normalize_history
from merval_agent.domain.models import Bar, MarketHistory, TechnicalMetrics
from merval_agent.domain.technical import calculate
from merval_agent.domain.technical_assessment import assess, narrative

AT = datetime(2026, 9, 16, 22, tzinfo=UTC)


def sample(ticker="GGAL", discarded=0):
    h = MarketHistory(
        ticker=ticker,
        range="6M",
        mode="live",
        source="fixture://history",
        fetched_at=AT,
        discarded_rows=discarded,
        bars=[
            Bar(
                date=date(2026, 9, 16) - timedelta(days=123 - i),
                open=100,
                high=101,
                low=99,
                close=100,
                volume=None,
            )
            for i in range(124)
        ],
    )
    m = TechnicalMetrics(
        current_price=100,
        sma20=110,
        sma50=120,
        ema12=108,
        ema26=110,
        rsi14=39.35,
        macd=-2,
        macd_signal=-3,
        macd_histogram=1,
        change_percent=10,
        sample_size=124,
    )
    return h, m


def test_bearish_trend_with_relative_recovery_not_global_mixed():
    h, m = sample()
    a = assess(h, m, AT)
    assert a.trend == a.conclusion == "BEARISH"
    assert a.momentum_state == "IMPROVING_BUT_BEARISH"
    assert a.confirmation == "UNCONFIRMED"
    assert a.signals["rsi14"].signal == "BEARISH"
    assert "zona neutral" in a.signals["rsi14"].explanation
    summary, details = narrative(a, 124)
    assert "bajo cero" in summary and "por encima de su señal" in summary
    assert "sin confirmar reversión" in summary and "sobreventa" not in details
    assert a.conflicts
    assert a.signals["period_change"].signal == "BULLISH"  # Context is not a reversal vote.


def test_bearish_recovery_is_improving_when_histogram_expands():
    h, m = sample()

    m = m.model_copy(
        update={
            "previous_macd_histogram": 0.5,
            "macd_histogram": 1.0,
        }
    )

    assessment = assess(h, m, AT)

    assert assessment.momentum_state == "IMPROVING_BUT_BEARISH"


def test_bearish_recovery_is_fading_when_histogram_contracts():
    h, m = sample()

    m = m.model_copy(
        update={
            "previous_macd_histogram": 2.0,
            "macd_histogram": 1.0,
        }
    )

    assessment = assess(h, m, AT)

    assert assessment.momentum_state == "RECOVERY_FADING_BUT_BEARISH"


def test_bearish_trend_and_momentum():
    h, m = sample()
    m.macd_signal, m.macd_histogram = -1, -1
    a = assess(h, m, AT)
    assert a.trend == a.momentum_state == a.conclusion == "BEARISH"
    assert a.confirmation == "ALIGNED"


def test_bullish_trend_losing_momentum():
    h, m = sample()
    m.sma20, m.sma50, m.ema12, m.ema26 = 90, 80, 92, 90
    m.macd, m.macd_signal, m.macd_histogram, m.rsi14 = 2, 3, -1, 60
    a = assess(h, m, AT)
    assert a.conclusion == a.trend == "BULLISH"
    assert a.momentum_state == "WEAKENING_BUT_BULLISH"
    assert "pérdida de impulso" in narrative(a, 124)[0]


def test_real_conflict_is_enumerated():
    h, m = sample()
    m.sma20 = 90  # Price above short average but below long average.
    a = assess(h, m, AT)
    assert a.conclusion == "MIXED"
    assert a.conflicts and "price_sma20" in a.conflicts[0]


def test_partial_summary_does_not_claim_unavailable_macd():
    h, _ = sample()
    h.bars = h.bars[-15:]
    h.bars = [
        b.model_copy(update={"open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100 + i})
        for i, b in enumerate(h.bars)
    ]
    a = assess(h, calculate(h.bars), AT)
    summary, _ = narrative(a, 15)
    assert a.status == "PARTIAL"
    assert a.signals["macd_zero"].signal == "UNAVAILABLE"
    assert "MACD" not in summary


@pytest.mark.parametrize("discarded,status", [(0, "COMPLETE"), (1, "PARTIAL")])
def test_same_essential_data_same_completeness(discarded, status):
    results = []
    for ticker in ("GGAL", "ALUA"):
        h, m = sample(ticker, discarded)
        a = assess(h, m, AT)
        assert a.status == status
        assert a.signals["volume"].signal == "UNAVAILABLE"
        assert m.average_volume is None
        results.append(a)
    assert results[0] == results[1]
    if discarded:
        assert "filas descartadas" in results[0].completion_reasons[0]


def test_upstream_missing_volume_field_is_optional(payload):
    for row in payload["data"]:
        del row["volume"]
    h = normalize_history(payload, "GGAL", "6M", "fixture://history")
    assert h.discarded_rows == 0
    assert all(b.volume is None for b in h.bars)
    assert calculate(h.bars).average_volume is None


def test_observed_alua_ohlc_defect_explains_partial(payload):
    # Public /history observation: close exceeded high; volume was present.
    payload["data"][0].update(open=952.5, high=964, low=942, close=964.5, volume=980408)
    h = normalize_history(payload, "GGAL", "6M", "fixture://same-rules-any-ticker")
    assert h.discarded_rows == 1 and len(h.bars) == 59


@pytest.mark.parametrize(
    "policy,included", [("history_only", False), ("include_provisional_ohlc", True)]
)
def test_quote_policy_and_dates(policy, included):
    h, _ = sample()
    payload = {
        "ok": True,
        "symbol": "GGAL",
        "market": "bCBA",
        "range": "6M",
        "fetchedAt": AT.isoformat(),
        "meta": {"source": "live", "stale": False},
        "data": [{**b.model_dump(mode="json"), "currency": "ARS"} for b in h.bars[:-1]],
    }
    quote = {
        "ok": True,
        "symbol": "GGAL",
        "market": "bCBA",
        "source": "live",
        "stale": False,
        "data": {
            "timestamp": "2026-09-16T18:00:00Z",
            "open": 100,
            "high": 110,
            "low": 99,
            "price": 105,
            "currency": "ARS",
            "volume": None,
        },
    }
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, json=payload if r.url.path.endswith("/history") else quote
            )
        )
    ) as http:
        history = ArgentinaMarketTrackerClient(
            http, "https://market.test", quote_policy=policy, clock=lambda: AT
        ).get_history("GGAL", "6M")
    a = assess(history, calculate(history.bars), AT)
    assert a.basis.quote_in_indicators is included
    assert a.basis.quote_provisional and a.basis.quote_price == 105
    assert a.basis.history_as_of == date(2026, 9, 15)
    assert a.basis.indicators_as_of == date(2026, 9, 16 if included else 15)
    assert len(history.bars) == (124 if included else 123)
    assert a.basis.history_closure == "UNVERIFIED"
    assert calculate(history.bars).current_price == (105 if included else 100)
