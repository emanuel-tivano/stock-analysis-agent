"""Opt-in public GGAL/BMA capture; no .env, credentials, or real LLM requests."""

import argparse
import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from merval_agent.adapters.bolsar import BolsarClient
from merval_agent.adapters.llm.fake import FakeLLMProvider
from merval_agent.adapters.market_tracker import ArgentinaMarketTrackerClient
from merval_agent.agents.equity_agent import EquityAgent
from merval_agent.api.app import create_app
from merval_agent.config import Settings
from merval_agent.domain.errors import ExternalServiceError
from merval_agent.domain.models import MarketHistory
from merval_agent.evaluation import RecordingRepository
from merval_agent.evaluation_reference import compare_metrics, reference_metrics
from merval_agent.evaluation_technical_v1 import snapshot_bytes
from merval_agent.retrieval.local import LocalMethodologyRetriever
from merval_agent.tools.registry import build_registry

BASE = "https://argentina-market-tracker.vercel.app"


def capture(output):
    output.mkdir(parents=True, exist_ok=False)
    requests = []

    def record(response):
        requests.append(
            {
                "url": str(response.url),
                "status": response.status_code,
                "received_at": datetime.now(UTC).isoformat(),
            }
        )

    rows = []
    for ticker in ("GGAL", "BMA"):
        row = {
            "ticker": ticker,
            "started_at": datetime.now(UTC).isoformat(),
            "timezone": "America/Argentina/Buenos_Aires",
            "data_mode": "live_attempt",
            "provider": "fake",
            "real_llm": "NOT_EVALUATED",
        }
        with httpx.Client(
            timeout=20, follow_redirects=True, event_hooks={"response": [record]}
        ) as http:
            try:
                h = ArgentinaMarketTrackerClient(http, BASE).get_history(ticker, "6M")
            except ExternalServiceError as exc:
                # Error bodies/headers are not evidence and can contain sensitive upstream data.
                cause = exc.__cause__
                row.update(
                    status="BLOCKED",
                    error_type=type(cause or exc).__name__,
                    reason="Public market source unavailable or invalid; no snapshot fabricated.",
                )
                rows.append(row)
                continue
        folder = output / ticker
        folder.mkdir()
        raw = snapshot_bytes(h)
        (folder / "snapshot.json").write_bytes(raw)
        row["snapshot_sha256"] = hashlib.sha256(raw).hexdigest()

        # Replay the exact normalized capture through the full HTTP/agent path.
        class SnapshotMarket:
            def get_history(self, symbol, range, market="bCBA"):
                assert symbol == ticker and range == "6M" and market == "bCBA"
                return MarketHistory.model_validate_json(raw)

        def reject_external_tool(request):
            raise AssertionError("Unexpected external tool")

        with httpx.Client(transport=httpx.MockTransport(reject_external_tool)) as offline:
            repo = RecordingRepository(str(folder / "trace.sqlite3"))
            agent = EquityAgent(
                FakeLLMProvider(),
                build_registry(
                    SnapshotMarket(),
                    BolsarClient(offline, "https://unused.test"),
                    LocalMethodologyRetriever(),
                ),
                repo,
            )
            with TestClient(create_app(agent=agent, settings=Settings.model_construct())) as client:
                response = client.post(
                    "/agent/run", json={"message": f"Analiza técnicamente {ticker}"}
                )
                response.raise_for_status()
                body = response.json()
        (folder / "response.json").write_text(
            json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        comparison = compare_metrics(body["technical"]["metrics"], reference_metrics(h.bars))
        (folder / "reference.json").write_text(json.dumps(comparison, indent=2), encoding="utf-8")
        row.update(
            status="PASS"
            if (all(v["pass"] for v in comparison.values()) and body["status"] == "ANSWER")
            else "FAIL",
            response_status=body["status"],
            assessment=body["technical"]["assessment"]["status"],
            currency=h.currency,
            count=len(h.bars),
            source=h.source,
            fetched_at=h.fetched_at.isoformat(),
            as_of=str(h.bars[-1].date),
            discarded_rows=h.discarded_rows,
            enrichment=h.enrichment_status,
            provisional=h.quote is not None,
            adjusted_prices="UNVERIFIED",
            reference="Independent Decimal geometric weights, SMA-seeded EMA and Wilder RSI",
        )
        rows.append(row)
    report = {"captured_at": datetime.now(UTC).isoformat(), "requests": requests, "cases": rows}
    (output / "capture.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/results")
        / ("technical-v1-live-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")),
    )
    args = parser.parse_args()
    if not args.live or os.getenv("RUN_LIVE_TESTS") != "1":
        parser.error("Public network requests require --live and RUN_LIVE_TESTS=1")
    logging.disable(logging.INFO)
    report = capture(args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(c["status"] == "PASS" for c in report["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
