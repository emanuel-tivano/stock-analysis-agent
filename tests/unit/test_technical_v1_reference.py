from datetime import date, timedelta

import pytest

from merval_agent.domain.models import Bar
from merval_agent.domain.technical import calculate
from merval_agent.evaluation_reference import compare_metrics, reference_metrics


@pytest.mark.parametrize("n", [0, 1, 11, 12, 14, 15, 19, 20, 25, 26, 33, 34, 49, 50, 60])
@pytest.mark.parametrize("pattern", ["up", "down", "flat", "oscillating"])
@pytest.mark.parametrize("volume", [None, 0, 100])
def test_independent_geometric_weight_reference(n, pattern, volume):
    values = {"up": lambda i: 100+i, "down": lambda i: 200-i,
              "flat": lambda i: 100, "oscillating": lambda i: 100+i/5+(-1)**i*(i%7)}
    bars = [Bar(date=date(2025, 1, 1)+timedelta(days=i*2),
                open=(p := values[pattern](i)), close=p, high=p+2, low=p-1, volume=volume)
            for i in range(n)]
    comparison = compare_metrics(calculate(bars).model_dump(), reference_metrics(bars))
    assert all(x["pass"] for x in comparison.values()), comparison


def test_manual_linear_seed_and_wilder_limits():
    bars = [Bar(date=date(2025, 1, 1)+timedelta(days=i), open=100+i,
                close=100+i, high=101+i, low=99+i, volume=0) for i in range(50)]
    m = calculate(bars)
    assert m.sma20 == 139.5 and m.sma50 == 124.5
    assert m.ema12 == pytest.approx(143.5)
    assert m.ema26 == pytest.approx(136.5)
    assert m.macd == pytest.approx(7)
    assert m.macd_signal == pytest.approx(7)
    assert m.macd_histogram == pytest.approx(0, abs=1e-12)
    assert m.rsi14 == 100 and m.average_volume == 0
