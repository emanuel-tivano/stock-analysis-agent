import pytest

from merval_agent.domain.technical import calculate, ema, macd, rsi, sma


def test_sma():
    assert sma([1, 2, 3, 4], 3) == 3
    assert sma([1], 20) is None


def test_ema_sma_seed():
    assert ema([2, 4, 6, 8], 3) == 6
    assert ema([1], 12) is None


def test_wilder_rsi_reference():
    prices = [
        44.34,
        44.09,
        44.15,
        43.61,
        44.33,
        44.83,
        45.10,
        45.42,
        45.84,
        46.08,
        45.89,
        46.03,
        45.61,
        46.28,
        46.28,
    ]
    assert rsi(prices) == pytest.approx(70.464135, abs=1e-6)
    assert rsi(prices + [46.00]) == pytest.approx(66.249619, abs=1e-6)


def test_rsi_edges():
    assert rsi(list(range(15))) == 100
    assert rsi(list(range(15, 0, -1))) == 0
    assert rsi([1] * 15) == 50
    assert rsi([1] * 14) is None


def test_macd_alignment_and_signal():
    assert macd(list(range(1, 35))) == pytest.approx((7, 7))
    assert macd(list(range(1, 27))) == (7, None)
    assert macd([2] * 25) == (None, None)
    assert macd([2] * 40) == (0, 0)


def test_calculate(bars):
    metrics = calculate(bars)
    assert metrics.sma20 == 150.5
    assert metrics.sma50 == 135.5
    assert metrics.change_percent == pytest.approx((160 / 101 - 1) * 100)
    assert metrics.period_high == 161
    assert metrics.period_low == 99
    assert metrics.average_volume == 1029.5
    assert calculate([]).sma20 is None


@pytest.mark.parametrize("fn", [sma, ema, rsi])
def test_invalid_period(fn):
    with pytest.raises(ValueError):
        fn([1, 2], 0)


def test_all_metrics_reference_and_one_point(bars):
    metrics = calculate(bars)
    assert metrics.ema12 == pytest.approx(154.5)
    assert metrics.ema26 == pytest.approx(147.5)
    assert metrics.macd == pytest.approx(7)
    assert metrics.macd_signal == pytest.approx(7)
    assert metrics.rsi14 == 100
    assert metrics.sample_size == 60
    single = calculate(bars[:1])
    assert single.sample_size == 1
    assert single.change_percent is None
    assert single.average_volume == 1000
    assert single.sma20 is single.rsi14 is single.macd is None
    assert calculate([]).sample_size == 0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_rejected_at_boundary(bars, value):
    from pydantic import ValidationError

    from merval_agent.domain.models import Bar

    for field in ("open", "high", "low", "close", "volume"):
        with pytest.raises(ValidationError):
            Bar.model_validate({**bars[0].model_dump(), field: value})


def test_volume_is_required(bars):
    from pydantic import ValidationError

    from merval_agent.domain.models import Bar

    data = bars[0].model_dump()
    del data["volume"]
    with pytest.raises(ValidationError):
        Bar.model_validate(data)
