"""Synthetic warm-up diagnostics; not a claim of TradingView equivalence."""

import runpy
from datetime import UTC, date, datetime, timedelta
from math import sin
from pathlib import Path

import pytest

from merval_agent.domain.models import Bar, MarketHistory

compare = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts/diagnose_macd_warmup.py")
)["compare"]


def histories():
    bars = []
    for i in range(250):
        value = 1000 + i + 100 * sin(i / 15)
        bars.append(
            Bar(
                date=date(2026, 1, 1) + timedelta(days=i),
                open=value,
                close=value,
                high=value,
                low=value,
                volume=100,
            )
        )
    long = MarketHistory(
        ticker="GGAL",
        range="1Y",
        bars=bars,
        source="fixture://warmup",
        fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
        resolved_variant="ajustada",
    )
    short = long.model_copy(update={"range": "6M", "bars": bars[-126:]})
    return short, long


def test_identical_tail_warmup_stabilizes_without_changing_formulas():
    short, long = histories()
    result = compare(short, long)
    sweep = {r["bars"]: r["max_abs_delta_to_1Y"] for r in result["warmup_sweep"]}
    assert result["overlap_identical"]
    assert sweep[200] < sweep[126]
    assert sweep[225] < 0.001
    assert result["comparisons"][0]["as_of"] == result["comparisons"][1]["as_of"]


def test_warmup_rejects_different_prices_or_variants():
    short, long = histories()
    with pytest.raises(ValueError, match="variants"):
        compare(short.model_copy(update={"resolved_variant": None}), long)
    changed = short.model_copy(deep=True)
    changed.bars[-1].close += 1
    with pytest.raises(ValueError, match="closes"):
        compare(changed, long)
