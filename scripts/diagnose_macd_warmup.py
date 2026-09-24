"""Opt-in market-only capture; replay saved histories without LLM or production changes."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from merval_agent.adapters.market_tracker import ArgentinaMarketTrackerClient
from merval_agent.domain.models import MarketHistory
from merval_agent.domain.technical import calculate

KEYS = ("ema12", "ema26", "macd", "macd_signal", "macd_histogram")
TV = {"macd": -176.59, "macd_signal": -141.55, "macd_histogram": -35.04}


def compare(short, long):
    """Compare identical overlapping closes and one shared terminal quote."""
    short_bars = short.bars[:-1] if short.enrichment_status == "appended" else short.bars
    long_bars = [b for b in long.bars if b.date <= short_bars[-1].date]
    overlap = {b.date: b.close for b in long_bars}
    if any(overlap.get(b.date) != b.close for b in short_bars):
        raise ValueError("Overlapping closes differ; cannot isolate warm-up")
    if short.resolved_variant != long.resolved_variant:
        raise ValueError("Price variants differ")
    if short.enrichment_status == "appended":
        long_bars.append(short.quote.bar)
    rows = []
    for label, bars in (("6M", short.bars), ("1Y", long_bars)):
        metrics = calculate(bars)
        values = {key: getattr(metrics, key) for key in KEYS}
        rows.append(
            {
                "range": label,
                "sample_size": len(bars),
                "as_of": str(bars[-1].date),
                **values,
                "delta_tv_2026_09_24": {k: values[k] - v for k, v in TV.items()},
            }
        )
    reference = calculate(long_bars)
    sweep = []
    for size in sorted(set([len(short.bars), 150, 175, 200, 225, len(long_bars)])):
        if size > len(long_bars):
            continue
        metrics = calculate(long_bars[-size:])
        sweep.append(
            {
                "bars": size,
                "max_abs_delta_to_1Y": max(
                    abs(getattr(metrics, k) - getattr(reference, k)) for k in KEYS
                ),
            }
        )
    return {
        "comparisons": rows,
        "warmup_sweep": sweep,
        "tv_reference": "User observations for 2026-09-24, not a synchronized TradingView feed",
        "overlap_identical": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    if args.live:
        with httpx.Client(timeout=30) as http:
            client = ArgentinaMarketTrackerClient(
                http, "https://argentina-market-tracker.vercel.app"
            )
            for label in ("6M", "1Y"):
                client.enrich_quote = label == "6M"
                h = client.get_history("GGAL", label)
                (args.directory / f"{label}.json").write_text(
                    h.model_dump_json(indent=2), encoding="utf-8"
                )
    histories = [
        MarketHistory.model_validate_json(
            (args.directory / f"{label}.json").read_text(encoding="utf-8")
        )
        for label in ("6M", "1Y")
    ]
    result = compare(*histories)
    result["diagnosed_at"] = datetime.now(UTC).isoformat()
    (args.directory / "diagnosis.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
