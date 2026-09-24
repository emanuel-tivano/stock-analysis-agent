"""Offline HTTP acceptance harness, separate from production decisions and old evals."""

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from merval_agent.adapters.bolsar import BolsarClient
from merval_agent.adapters.llm.fake import FakeLLMProvider
from merval_agent.adapters.market_tracker import ArgentinaMarketTrackerClient
from merval_agent.agents.equity_agent import EquityAgent
from merval_agent.api.app import create_app
from merval_agent.config import Settings
from merval_agent.domain.models import FinalAnalysis
from merval_agent.domain.technical_assessment import narrative
from merval_agent.evaluation import RecordingRepository
from merval_agent.evaluation_reference import compare_metrics, reference_metrics
from merval_agent.retrieval.local import LocalMethodologyRetriever
from merval_agent.tools.registry import build_registry

VERSION = "technical-v1-closure-1"
AT = datetime(2026, 9, 16, 22, tzinfo=UTC)  # Fixture clock only, never a production policy.
ROOT = Path(__file__).resolve().parents[2]
AXES = (
    "schema",
    "tool_selection",
    "tool_arguments",
    "classification",
    "numbers",
    "evidence",
    "contradictions",
    "insufficiency",
    "external_errors",
    "response_quality",
    "unsupported_claims",
    "tracing",
)


def load_cases():
    return [
        json.loads(line)
        for line in (ROOT / "evals/technical_v1_dataset.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]


def snapshot_bytes(history):
    # Same byte serialization as the production TOOL_SUCCEEDED snapshot hash.
    return history.model_dump_json().encode("utf-8")


def fixture_payload(case):
    """Short, readable constructions: ramp, flat, late reversal, or one impulse."""
    n = case.get("n", 60)
    pattern = case.get("pattern", "up")
    prices = {
        "up": [100 + i for i in range(n)],
        "down": [200 - i for i in range(n)],
        "flat": [100] * n,
        "mixed": [100 + i for i in range(n - 5)] + [145, 135, 125, 115, 105],
        "cross": [100] * (n - 2) + [99, 110],
    }[pattern]
    last = AT.date() - timedelta(days=case.get("age", 1))
    dates = []
    while len(dates) < n:
        if last.weekday() < 5:
            dates.append(last)
        last -= timedelta(days=1)
    rows = [
        {
            "date": day.isoformat(),
            "open": price,
            "high": price + 1,
            "low": price - 1,
            "close": price,
            "volume": case.get("volume", 100),
            "currency": "peso_Argentino",
        }
        for day, price in zip(reversed(dates), prices)
    ]
    if case.get("volume_spike"):
        rows[-1]["volume"] = 200
    if case.get("bad_row"):
        rows[0]["high"] = 1
    if case.get("duplicate"):
        rows[-1]["date"] = rows[-2]["date"]
    if case.get("gap"):
        rows.pop(n // 2)
    return {
        "ok": True,
        "symbol": case.get("ticker", "GGAL"),
        "market": "bCBA",
        "range": "6M",
        "fetchedAt": AT.isoformat(),
        "meta": {"source": "live", "stale": False},
        "data": rows,
    }


def fixture_transport(case):
    payload = fixture_payload(case)

    def handler(request):
        if request.url.path.endswith("/history"):
            if case.get("failure") == "timeout":
                raise httpx.ReadTimeout("fixture timeout", request=request)
            if case.get("failure") == "payload":
                return httpx.Response(200, content=b"not-json")
            return httpx.Response(case.get("http", 200), json=payload)
        if request.url.path.endswith("/quote"):
            if not case.get("quote"):
                return httpx.Response(503, json={"ok": False})
            quote_day = (
                AT.date()
                if case["quote"] != "same"
                else datetime.fromisoformat(payload["data"][-1]["date"]).date()
            )
            price = payload["data"][-1]["close"] + 1
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "symbol": case.get("ticker", "GGAL"),
                    "market": "bCBA",
                    "source": "live",
                    "stale": False,
                    "data": {
                        "timestamp": quote_day.isoformat() + "T18:00:00Z",
                        "open": price,
                        "price": price,
                        "high": price + 1,
                        "low": price - 1,
                        "volume": None,
                        "currency": "USD" if case["quote"] == "invalid" else "peso_Argentino",
                    },
                },
            )
        raise AssertionError(f"Unexpected nontechnical endpoint {request.url.path}")

    return httpx.MockTransport(handler)


def score(case, state, result, registry, persisted, http_ok=True):
    """Per-axis booleans or NOT_EVALUATED. Expectations are authored in JSONL."""
    axes = dict.fromkeys(AXES, "NOT_EVALUATED")
    axes["schema"] = http_ok and FinalAnalysis.model_validate(result.model_dump()) == result
    calls = state.tool_calls
    expected_tools = case["tools"]
    axes["tool_selection"] = [c.name for c in calls] == expected_tools
    args_ok = True
    for c in calls:
        try:
            registry.tools[c.name].args.model_validate(c.arguments)
        except (KeyError, ValueError):
            args_ok = False
        expected = (
            {"query": case["input"]}
            if c.name == "resolve_asset"
            else {"ticker": case.get("ticker", "GGAL"), "range": "6M"}
            if c.name == "get_market_history"
            else {"ticker": case.get("ticker", "GGAL")}
        )
        args_ok = args_ok and c.arguments == expected
    axes["tool_arguments"] = args_ok
    a = result.technical.assessment
    axes["classification"] = result.status == case["status"]
    if case.get("technical_status"):
        axes["classification"] &= result.technical.status == case["technical_status"]
    if case.get("assessment"):
        axes["classification"] &= bool(a and a.status == case["assessment"])
    if case.get("conclusion"):
        axes["classification"] &= bool(
            a
            and a.conclusion == case["conclusion"]
            and result.technical.status == case["conclusion"]
        )
    h = state.technical_data
    numeric = {}
    if h and result.technical.metrics:
        numeric = compare_metrics(result.technical.metrics.model_dump(), reference_metrics(h.bars))
        axes["numbers"] = all(v["pass"] for v in numeric.values())
        if h.quote and h.enrichment_status == "appended":
            historic = result.technical.history_only_metrics
            axes["numbers"] &= bool(
                historic
                and all(
                    v["pass"]
                    for v in compare_metrics(
                        historic.model_dump(), reference_metrics(h.bars[:-1])
                    ).values()
                )
            )
        axes["evidence"] = bool(
            result.as_of == h.bars[-1].date
            and result.sources
            and result.technical.evidence
            and result.technical.evidence[0].metadata["currency"] == h.currency
            and a.basis.history_fetched_at == h.fetched_at
        )
        if case.get("enrichment"):
            axes["evidence"] &= h.enrichment_status == case["enrichment"]
        if h.quote:
            axes["evidence"] &= a.basis.quote_provisional and h.quote.bar.volume is None
        if case.get("volume_signal"):
            axes["evidence"] &= a.signals["volume"].signal == case["volume_signal"]
    if case.get("conclusion") == "MIXED":
        axes["contradictions"] = bool(
            a and a.conflicts and a.conclusion == "MIXED" and "mixta" in result.executive_summary
        )
    if case["status"] == "ABSTAIN" or case.get("assessment") == "PARTIAL":
        axes["insufficiency"] = result.status == case["status"] and bool(
            result.data_quality.missing_information
            or (a and a.missing_indicators)
            or "integral" in result.executive_summary
        )
        if case.get("assessment") == "PARTIAL":
            axes["insufficiency"] = result.status == "ANSWER" and bool(
                a.completion_reasons and result.technical.metrics
            )
    if case["status"] == "ERROR":
        axes["external_errors"] = (
            result.status == "ERROR" and bool(result.errors) and a.confidence == "UNAVAILABLE"
        )
    prose = result.executive_summary + " " + result.technical.interpretation
    axes["response_quality"] = bool(result.executive_summary.strip())
    if result.status == "ANSWER":
        axes["response_quality"] &= bool(
            result.company_name
            and result.ticker
            and str(result.as_of) in result.executive_summary
            and "Muestra:" in result.executive_summary
            and "recomendación financiera personalizada" in prose
            and a.confidence in ("HIGH", "MEDIUM", "LOW")
            and result.technical.limitations
        )
    # Exact deterministic narrative provenance + restricted grammar, not an LLM judge.
    axes["unsupported_claims"] = not bool(
        re.search(
            r"\b(?:compr[aá]|vend[eé]|garantizado|garantizada|objetivo de precio)\b", prose, re.I
        )
    )
    if result.status == "ANSWER":
        axes["unsupported_claims"] &= result.technical.narrative_origin == "deterministic"
        summary, interpretation = narrative(a, result.technical.metrics.sample_size)
        axes["unsupported_claims"] &= (
            result.executive_summary == summary
            and result.technical.interpretation == interpretation
        )
    axes["tracing"] = bool(
        persisted
        and persisted[0] == case["input"]
        and persisted[1] == result.executive_summary
        and state.trace_events
        and all(e["trace_id"] == result.trace_id for e in state.trace_events)
        and len([e for e in state.trace_events if e["event"] in ("TOOL_SUCCEEDED", "TOOL_FAILED")])
        == len(calls)
    )
    if h:
        hashes = [
            e["market_data"]["snapshot_sha256"] for e in state.trace_events if "market_data" in e
        ]
        axes["tracing"] &= hashlib.sha256(snapshot_bytes(h)).hexdigest() in hashes
    return {
        "id": case["id"],
        "axes": {k: "PASS" if v is True else "FAIL" if v is False else v for k, v in axes.items()},
        "reference": numeric,
    }


def evaluate_case(case, output):
    output.mkdir(parents=True, exist_ok=False)
    repo = RecordingRepository(str(output / "trace.sqlite3"))
    with httpx.Client(transport=fixture_transport(case)) as http:
        registry = build_registry(
            ArgentinaMarketTrackerClient(http, "https://market.test", clock=lambda: AT),
            BolsarClient(http, "https://bolsar.test"),
            LocalMethodologyRetriever(),
        )
        agent = EquityAgent(FakeLLMProvider(), registry, repo, clock=lambda: AT)
        with TestClient(create_app(agent=agent, settings=Settings.model_construct())) as client:
            response = client.post("/agent/run", json={"message": case["input"]})
            result = FinalAnalysis.model_validate(response.json())
        with sqlite3.connect(output / "trace.sqlite3") as db:
            saved = db.execute(
                "SELECT user_request,summary FROM analyses WHERE trace_id=?", (result.trace_id,)
            ).fetchone()
        row = score(
            case,
            repo.state,
            result,
            registry,
            saved,
            response.status_code == 200 and "charset=utf-8" in response.headers["content-type"],
        )
    (output / "response.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    if repo.state.technical_data:
        raw = snapshot_bytes(repo.state.technical_data)
        (output / "snapshot.json").write_bytes(raw)
        row["snapshot_sha256"] = hashlib.sha256(raw).hexdigest()
    (output / "evaluation.json").write_text(
        json.dumps(row, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return row


def evaluate(output):
    output.mkdir(parents=True, exist_ok=False)
    rows = [evaluate_case(case, output / case["id"]) for case in load_cases()]
    report = {
        "dataset_version": VERSION,
        "provider": "fake",
        "model": None,
        "prompt_version": "NOT_APPLICABLE_FAKE",
        "timestamp": datetime.now(UTC).isoformat(),
        "fixture_clock": AT.isoformat(),
        "data_mode": "fixtures",
        "real_provider": "NOT_EVALUATED",
        "provider_failures": 0,
        "passed": sum("FAIL" not in row["axes"].values() for row in rows),
        "total": len(rows),
        "cases": rows,
        "axes": {
            axis: {
                status: sum(row["axes"][axis] == status for row in rows)
                for status in ("PASS", "FAIL", "NOT_EVALUATED")
            }
            for axis in AXES
        },
    }
    (output / "evaluation.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report
