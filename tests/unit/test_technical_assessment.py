from datetime import UTC, date, datetime, timedelta

import pytest

from merval_agent.domain.models import Bar, MarketHistory, QuoteSnapshot
from merval_agent.domain.policy import MAX_PROVIDER_CLOCK_AHEAD
from merval_agent.domain.technical import calculate
from merval_agent.domain.technical_assessment import assess, stale_date

AT = datetime(2026, 9, 16, 22, tzinfo=UTC)


def history(count=124, direction=1, last=date(2026, 9, 16)):
    dates = []
    day = last
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day)
        day -= timedelta(days=1)
    prices = [1000 + direction * (i * i / 100 + i) for i in range(count)]
    return MarketHistory(
        ticker="GGAL",
        range="6M",
        source="fixture://technical-124",
        provider_fetched_at=AT,
        received_at=AT,
        mode="live",
        currency="ARS",
        bars=[
            Bar(date=d, open=p, close=p, low=p - 1, high=p + 1, volume=1000)
            for d, p in zip(reversed(dates), prices)
        ],
    )


@pytest.mark.parametrize(
    "count,status",
    [
        (124, "COMPLETE"),
        (50, "COMPLETE"),
        (49, "PARTIAL"),
        (34, "PARTIAL"),
        (15, "PARTIAL"),
        (14, "INSUFFICIENT_DATA"),
        (1, "INSUFFICIENT_DATA"),
        (0, "INSUFFICIENT_DATA"),
    ],
)
def test_sample_boundaries(count, status):
    h = history(count)
    a = assess(h, calculate(h.bars), AT)
    assert a.status == status
    if count == 15:
        assert a.signals["rsi14"].signal == "BULLISH"
        assert "50 observaciones" in a.missing_indicators["sma50"]
        assert "34 observaciones" in a.missing_indicators["macd_signal"]


def test_optional_volume_does_not_degrade_price_analysis():
    h = history()
    h.bars[-1].volume = None
    metrics = calculate(h.bars)
    assert metrics.average_volume is None
    assert assess(h, metrics, AT).status == "COMPLETE"


@pytest.mark.parametrize("direction,signal", [(1, "BULLISH"), (-1, "BEARISH"), (0, "NEUTRAL")])
def test_consistent_signals(direction, signal):
    h = history(direction=direction)
    a = assess(h, calculate(h.bars), AT)
    assert a.trend == a.momentum == a.conclusion == signal
    assert not a.conflicts


def test_contradiction_is_explicit():
    h = history()
    m = calculate(h.bars).model_copy(
        update={"rsi14": 42.04, "macd": -90.34, "macd_signal": -121.28, "macd_histogram": 30.94}
    )
    a = assess(h, m, AT)
    assert a.status == "COMPLETE"
    assert a.conclusion == a.momentum == "MIXED"
    assert a.conflicts
    assert a.signals["macd_signal"].signal == "BULLISH"
    assert a.signals["rsi14"].signal == "BEARISH"
    assert "zona neutral" in a.signals["rsi14"].explanation


@pytest.mark.parametrize(
    "rsi,zone,signal",
    [
        (70, "sobrecompra", "BULLISH"),
        (30, "sobreventa", "BEARISH"),
        (50, "zona neutral", "NEUTRAL"),
        (55, "zona neutral", "BULLISH"),
        (45, "zona neutral", "BEARISH"),
    ],
)
def test_rsi_zones(rsi, zone, signal):
    h = history()
    m = calculate(h.bars).model_copy(update={"rsi14": rsi})
    s = assess(h, m, AT).signals["rsi14"]
    assert s.signal == signal and zone in s.explanation


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), -1, None])
def test_invalid_price_never_generates_signals(value):
    h = history()
    m = calculate(h.bars)
    h.bars[-1] = h.bars[-1].model_copy(update={"close": value})
    a = assess(h, m, AT)
    assert a.status == "INVALID_DATA" and not a.signals


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_metrics_invalid(value):
    h = history()
    m = calculate(h.bars).model_copy(update={"sma50": value})
    assert assess(h, m, AT).status == "INVALID_DATA"


@pytest.mark.parametrize(
    "change", ["duplicate", "unordered", "future", "future_receipt", "history_after_receipt"]
)
def test_invalid_dates(change):
    h = history()
    m = calculate(h.bars)
    if change == "duplicate":
        h.bars[-1] = h.bars[-2]
    if change == "unordered":
        h.bars[1], h.bars[2] = h.bars[2], h.bars[1]
    if change == "future":
        h.bars[-1] = h.bars[-1].model_copy(update={"date": date(2026, 9, 17)})
    if change == "future_receipt":
        h.received_at = AT + timedelta(days=1)
    if change == "history_after_receipt":
        h.received_at = AT - timedelta(days=1)
    assert assess(h, m, AT).status == "INVALID_DATA"


@pytest.mark.parametrize(
    "ahead",
    [
        timedelta(microseconds=95_820),
        timedelta(seconds=1, microseconds=112_547),
        MAX_PROVIDER_CLOCK_AHEAD,
    ],
)
def test_provider_clock_ahead_within_limit_is_accepted(ahead):
    h = history()
    h.provider_fetched_at = h.received_at + ahead
    a = assess(h, calculate(h.bars), AT)
    assert a.status == "COMPLETE"
    assert a.basis.history_provider_clock_skew_ms == pytest.approx(ahead.total_seconds() * 1000)


@pytest.mark.parametrize(
    "ahead", [MAX_PROVIDER_CLOCK_AHEAD + timedelta(microseconds=1), timedelta(minutes=1)]
)
def test_provider_clock_ahead_over_limit_is_invalid(ahead):
    h = history()
    h.provider_fetched_at = h.received_at + ahead
    a = assess(h, calculate(h.bars), AT)
    assert a.status == "INVALID_DATA"
    assert a.freshness == "INVALID"
    assert "reloj remoto" in a.warnings[0]


def test_old_provider_timestamp_is_valid_cache_age():
    h = history()
    h.provider_fetched_at = h.received_at - timedelta(days=1)
    assert assess(h, calculate(h.bars), AT).status == "COMPLETE"


def test_equivalent_timezone_instants_do_not_create_skew():
    market_at = datetime.fromisoformat("2026-09-16T19:00:00-03:00")
    h = history()
    h.provider_fetched_at = market_at
    a = assess(h, calculate(h.bars), market_at)
    assert a.status == "COMPLETE"
    assert a.basis.history_provider_clock_skew_ms == 0


def test_quote_observed_after_local_receipt_is_invalid():
    h = history(last=date(2026, 9, 15))
    quote_bar = Bar(date=date(2026, 9, 16), open=120, high=121, low=119, close=120, volume=1000)
    quote = QuoteSnapshot(
        bar=quote_bar,
        source="fixture://quote",
        observed_at=AT + timedelta(microseconds=1),
        provider_fetched_at=AT,
        received_at=AT,
        currency="ARS",
    )
    h = h.model_copy(
        update={
            "bars": [*h.bars, quote_bar],
            "quote": quote,
            "enrichment_status": "appended",
        }
    )
    assert assess(h, calculate(h.bars), AT).status == "INVALID_DATA"


def test_stale_and_demo_separate_from_insufficiency():
    h = history(last=date(2026, 9, 1))
    assert assess(h, calculate(h.bars), AT).status == "STALE"
    h = history().model_copy(update={"mode": "demo"})
    assert assess(h, calculate(h.bars), AT).status == "UNVERIFIED"


def test_last_session_weekend_and_explicit_holiday():
    friday = date(2026, 9, 11)
    for day in (date(2026, 9, 12), date(2026, 9, 13), date(2026, 9, 14)):
        assert not stale_date(friday, day, 0)
    assert not stale_date(friday, date(2026, 9, 15), 0, frozenset({date(2026, 9, 14)}))
    assert stale_date(friday, date(2026, 9, 15), 0)
    # Conservative default tolerates an unconfigured ordinary holiday break.
    assert not stale_date(friday, date(2026, 9, 15), 7)


def test_missing_calculation_not_zero_and_sample_mismatch():
    h = history()
    m = calculate(h.bars).model_copy(update={"macd_signal": None, "macd_histogram": None})
    a = assess(h, m, AT)
    assert a.status == "PARTIAL"
    assert a.signals["macd_signal"].signal == "UNAVAILABLE"
    assert "ventana suficiente" in a.missing_indicators["macd_signal"]
    assert m.macd_signal is None
    assert assess(h, m.model_copy(update={"sample_size": 123}), AT).status == "INVALID_DATA"


def test_discarded_rows_reduce_quality():
    h = history().model_copy(update={"discarded_rows": 2})
    a = assess(h, calculate(h.bars), AT)
    assert a.status == "PARTIAL" and a.confidence == "MEDIUM"
