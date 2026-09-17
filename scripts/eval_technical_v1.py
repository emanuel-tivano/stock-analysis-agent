"""Reproducible offline technical demo. Never replaces an existing run directory."""

import argparse
import logging
from datetime import UTC, datetime
from pathlib import Path

from merval_agent.evaluation_technical_v1 import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/results")
        / ("technical-v1-fake-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")),
    )
    args = parser.parse_args()
    logging.disable(logging.INFO)
    result = evaluate(args.output)
    print(f"Fake technical V1: {result['passed']}/{result['total']}; {args.output}")
    for row in result["cases"]:
        failures = [axis for axis, status in row["axes"].items() if status == "FAIL"]
        if failures:
            print(row["id"], failures)
    return 0 if result["passed"] == result["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
