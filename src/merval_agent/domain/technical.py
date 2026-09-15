"""Daily bars; SMA-seeded EMA; Wilder RSI; no rounding before presentation."""

from statistics import fmean

from .models import Bar, TechnicalMetrics


def sma(values: list[float], period: int) -> float | None:
    if period <= 0:
        raise ValueError("period must be positive")
    return fmean(values[-period:]) if len(values) >= period else None


def ema_series(values: list[float], period: int) -> list[float]:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period:
        return []
    result = [fmean(values[:period])]
    alpha = 2 / (period + 1)
    for value in values[period:]:
        result.append(alpha * value + (1 - alpha) * result[-1])
    return result


def ema(values: list[float], period: int) -> float | None:
    series = ema_series(values, period)
    return series[-1] if series else None


def rsi(values: list[float], period: int = 14) -> float | None:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) <= period:
        return None
    changes = [b - a for a, b in zip(values, values[1:])]
    gain = fmean(max(d, 0) for d in changes[:period])
    loss = fmean(max(-d, 0) for d in changes[:period])
    for delta in changes[period:]:
        gain = (gain * (period - 1) + max(delta, 0)) / period
        loss = (loss * (period - 1) + max(-delta, 0)) / period
    if loss == 0:
        return 100.0 if gain else 50.0
    return 100 - 100 / (1 + gain / loss)


def macd(values: list[float]) -> tuple[float | None, float | None]:
    fast, slow = ema_series(values, 12), ema_series(values, 26)
    line = [a - b for a, b in zip(fast[14:], slow)]
    return (line[-1], ema(line, 9)) if line else (None, None)


def calculate(bars: list[Bar]) -> TechnicalMetrics:
    if not bars:
        return TechnicalMetrics()
    values = [b.close for b in bars]
    line, signal = macd(values)
    return TechnicalMetrics(
        sma20=sma(values, 20),
        sma50=sma(values, 50),
        ema12=ema(values, 12),
        ema26=ema(values, 26),
        rsi14=rsi(values),
        macd=line,
        macd_signal=signal,
        change_percent=(values[-1] / values[0] - 1) * 100 if len(values) > 1 else None,
        period_high=max(b.high for b in bars),
        period_low=min(b.low for b in bars),
        average_volume=fmean(b.volume for b in bars),
        sample_size=len(bars),
    )
