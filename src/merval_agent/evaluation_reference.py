"""Evaluation-only Decimal oracle; no imports from production indicator code.

EMA and Wilder smoothing use explicit geometric weights, not recursive updates.
Dates are observations, not an invented exchange calendar. Prices are unadjusted
as supplied. The oracle intentionally shares the documented SMA seed convention.
"""

from decimal import Decimal, localcontext
from math import isclose


def reference_metrics(bars) -> dict:
    with localcontext() as ctx:
        ctx.prec = 50
        return _reference(bars)


def _reference(bars):
    d = lambda x: Decimal(str(x))
    prices = [d(b.close) for b in bars]

    def average(xs):
        return sum(xs, Decimal(0)) / len(xs)

    def weighted(xs, period, alpha):
        if len(xs) < period:
            return None
        tail = xs[period:]
        decay = 1 - alpha
        return average(xs[:period]) * decay ** len(tail) + sum(
            (alpha * x * decay ** (len(tail)-1-i) for i, x in enumerate(tail)), Decimal(0)
        )

    def ema(xs, period):
        return weighted(xs, period, Decimal(2) / (period+1))

    line = [ema(prices[:n], 12) - ema(prices[:n], 26) for n in range(26, len(prices)+1)]
    signal = ema(line, 9)
    rsi = None
    if len(prices) >= 15:
        changes = [b-a for a, b in zip(prices, prices[1:])]
        gains = weighted([max(x, Decimal(0)) for x in changes], 14, Decimal(1)/14)
        losses = weighted([max(-x, Decimal(0)) for x in changes], 14, Decimal(1)/14)
        rsi = (100 if gains else 50) if losses == 0 else 100 - 100 / (1+gains/losses)
    result = {
        "current_price": prices[-1] if prices else None,
        "sma20": average(prices[-20:]) if len(prices) >= 20 else None,
        "sma50": average(prices[-50:]) if len(prices) >= 50 else None,
        "ema12": ema(prices, 12), "ema26": ema(prices, 26), "rsi14": rsi,
        "macd": line[-1] if line else None, "macd_signal": signal,
        "macd_histogram": line[-1]-signal if signal is not None else None,
        "change_percent": (prices[-1]-prices[0])*100/prices[0] if len(prices)>1 else None,
        "period_high": max(d(b.high) for b in bars) if bars else None,
        "period_low": min(d(b.low) for b in bars) if bars else None,
        "average_volume": average([d(b.volume) for b in bars])
            if bars and all(b.volume is not None for b in bars) else None,
        "sample_size": len(bars),
    }
    return {k: float(v) if v is not None else None for k, v in result.items()}


def compare_metrics(actual: dict, expected: dict) -> dict:
    """Check every field, including unavailable values; retain numerical errors."""
    return {k: {"actual": actual.get(k), "reference": v,
                "absolute_error": abs(actual[k]-v) if v is not None and actual.get(k) is not None else None,
                "pass": actual.get(k) is None if v is None else (
                    actual.get(k) is not None and isclose(actual[k], v, rel_tol=1e-10, abs_tol=1e-9))}
            for k, v in expected.items()}
