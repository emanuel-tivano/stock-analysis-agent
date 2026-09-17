"""Semantic evaluation outside EquityAgent; identical fixture data for Fake and Real."""

import hashlib
import json
import math
from datetime import UTC, date, datetime, timedelta
from ipaddress import ip_address
from pathlib import Path
from time import perf_counter, sleep
from urllib.parse import urlsplit

import httpx

from merval_agent.adapters.bolsar import BolsarClient
from merval_agent.adapters.llm.context import get_system_instructions
from merval_agent.adapters.llm.fake import FakeLLMProvider
from merval_agent.adapters.market_tracker import ArgentinaMarketTrackerClient
from merval_agent.agents.equity_agent import EquityAgent
from merval_agent.bootstrap import build_provider
from merval_agent.evaluation_rate_limit import SequentialLLMRateLimiter
from merval_agent.memory.sqlite import SQLiteRepository
from merval_agent.retrieval.local import LocalMethodologyRetriever
from merval_agent.tools.registry import build_registry

DATASET_VERSION = "technical-v3"
ROOT = Path(__file__).resolve().parents[2]


def provider_environment(base_url):
    """Label loopback endpoints without persisting URLs or resolving hostnames."""
    try:
        host = urlsplit(base_url).hostname
        if host and host.lower() == "localhost":
            return "local"
        if host and ip_address(host).is_loopback:
            return "local"
    except ValueError:
        pass
    return "remote"


def load_cases():
    return [
        json.loads(line)
        for line in (ROOT / "evals/real_llm_dataset.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def fixture_transport(case):
    def handler(request):
        if request.url.path.endswith("/quote"):
            return httpx.Response(503, json={"ok": False})
        if "/history" in request.url.path:
            count = case.get("bar_count", 60)
            bars = [
                {
                    "date": str(date.today() - timedelta(days=count - 1 - i)),
                    "open": 100 + i,
                    "high": 102 + i,
                    "low": 99 + i,
                    "close": 101 + i,
                    "volume": 1000 + i,
                    "currency": "peso_Argentino",
                }
                for i in range(count)
            ]
            return httpx.Response(
                case.get("market_status", 200),
                json={
                    "ok": True,
                    "symbol": request.url.path.split("/")[-2],
                    "market": "bCBA",
                    "range": request.url.params["range"],
                    "fetchedAt": datetime.now(UTC).isoformat(),
                    "meta": {"source": "live", "stale": False},
                    "data": bars,
                },
            )
        return httpx.Response(
            200,
            text="<table><tr><th>Fecha</th><th>Emisor</th><th>Especie</th><th>Referencias</th><th>Archivo</th></tr>"
            + (
                "<tr><td>20/08/2026</td><td>Pampa</td><td>PAMP</td><td>Estados Financieros</td>"
                '<td><a href="https://ws.bolsar.info/descarga/?id=102">Descargar</a></td></tr>'
                if case.get("documents")
                else ""
            )
            + "</table>",
        )

    return httpx.MockTransport(handler)


class RecordingRepository:
    def __init__(self, path):
        self.sqlite = SQLiteRepository(path)
        self.state = None

    def save(self, state, result):
        self.state = state
        self.sqlite.save(state, result)


def provider_failure_details(attempts):
    """Allowlist telemetry only; never serialize error messages or provider payloads."""
    failures = [e for e in attempts if e["event"] == "LLM_FAILED"]
    known_codes = {
        "INVALID_ARGUMENT",
        "UNAUTHENTICATED",
        "PERMISSION_DENIED",
        "RESOURCE_EXHAUSTED",
        "UNAVAILABLE",
        "TIMEOUT",
        "TRANSPORT_ERROR",
        "INVALID_RESPONSE",
        "NO_CANDIDATES",
        "INVALID_CANDIDATE",
        "UNUSABLE_FINISH_REASON",
        "NO_TEXT",
        "LLM_FAILURE",
    } | {f"HTTP_{status}" for status in range(100, 600)}
    return {
        "http_statuses": [
            e.get("http_status")
            if type(e.get("http_status")) is int and 100 <= e["http_status"] <= 599
            else None
            for e in failures
        ],
        "codes": [
            e.get("provider_error_code")
            if e.get("provider_error_code") in known_codes
            else "LLM_FAILURE"
            for e in failures
        ],
    }


def classify_result(result, attempts, task_success):
    if result.status != "ERROR":
        return "PASS" if task_success else "FAIL"
    errors = {e.code for e in result.errors}
    if errors & {"INTERNAL_ERROR", "PERSISTENCE_FAILURE"}:
        return "NOT_EVALUATED"
    if errors & {"INVALID_DECISION", "DECISION_BUDGET_EXHAUSTED", "MAX_STEPS_EXCEEDED"}:
        return "FAIL"
    if "LLM_FAILURE" in errors and attempts:
        if attempts[-1]["event"] == "LLM_FAILED":
            return "PROVIDER_ERROR"
        if attempts[-1]["event"] == "DECISION_VALIDATION_FAILED":
            return "FAIL"
    if "EXTERNAL_SERVICE" in errors:
        return "PASS" if task_success else "FAIL"
    return "NOT_EVALUATED"


def score_case(case, state, result, latency):
    labels = [
        c.name + (":" + c.arguments["source"] if c.name == "search_methodology" else "")
        for c in state.tool_calls
    ]
    forbidden = set(case["forbidden_tools"])
    failed = [e for e in state.trace_events if e["event"] == "DECISION_VALIDATION_FAILED"]
    violations = sum(x in forbidden for x in labels) + sum(
        (e.get("tool_name") + (":" + e["source"] if e.get("source") else "")) in forbidden
        for e in failed
        if e.get("tool_name")
    )
    required = set(case["expected_tools"])
    if "get_latest_financial_statement" in required and "list_financial_documents" in labels:
        required.remove("get_latest_financial_statement")
    # A benchmark-permitted clarification/abstention with no identifiable asset
    # does not require a redundant catalog lookup. Never waive data requirements.
    if (
        result.status in ("CLARIFY", "ABSTAIN")
        and result.status in case["expected_status"]
        and case.get("expected_asset") is None
        and result.ticker is None
        and required <= {"resolve_asset"}
    ):
        required.discard("resolve_asset")
    # Methodology cannot restore missing mandatory input data. An expected technical
    # ERROR after that data tool failed need not retrieve interpretive methodology.
    failed_tools = {o.tool_name for o in state.observations if not o.success}
    if result.status == "ERROR" and result.status in case["expected_status"]:
        if not state.technical_data and "get_market_history" in failed_tools:
            required.discard("search_methodology:murphy")
        if not state.financial_data and failed_tools & {
            "get_latest_financial_statement",
            "list_financial_documents",
        }:
            required.discard("search_methodology:graham")
    correct_tools = required <= set(labels) and not violations
    status_correct = result.status in case["expected_status"]
    abstentions_correct = set(case.get("expected_abstention", [])) <= set(
        result.data_quality.abstentions
    )
    calls = len(state.tool_calls)
    seen = set()
    duplicates = 0
    for call, observation in zip(
        state.tool_calls, (o for o in state.observations if o.tool_name != "decision")
    ):
        key = observation.operation_key or (call.name, json.dumps(call.arguments, sort_keys=True))
        duplicates += key in seen
        if observation.success:
            seen.add(key)
    duplicates += sum(bool(e.get("duplicate_tool_call")) for e in failed)
    attempts = [
        e
        for e in state.trace_events
        if e["event"] in ("LLM_SUCCEEDED", "LLM_FAILED", "DECISION_VALIDATION_FAILED")
    ]
    usage = [e["usage"] for e in attempts if e.get("usage")]

    def tokens(key):
        values = [u[key] for u in usage if key in u]
        return sum(values) if values else None

    dimension_correct = (
        result.analysis_type == case.get("expected_analysis_type", result.analysis_type)
        and all(
            c.arguments.get("range") == "6M"
            for c in state.tool_calls
            if c.name == "get_market_history"
        )
        and (result.analysis_type != "technical" or result.fundamental.status == "NOT_REQUESTED")
        and (result.analysis_type != "fundamental" or result.technical.status == "NOT_REQUESTED")
        and result.fundamental.metrics is None
        and all(e.kind == "DEMO" for e in state.methodology_evidence)
        and (not case.get("documents") or bool(state.financial_data))
    )
    row = {
        "id": case["id"],
        "case": case["id"],
        "trace_id": result.trace_id,
        "status": result.status,
        "ticker": result.ticker,
        "tools": labels,
        "task_success": correct_tools
        and status_correct
        and abstentions_correct
        and dimension_correct
        and not duplicates
        and result.ticker in case.get("allowed_assets", [case.get("expected_asset")]),
        "tools_correct": correct_tools and not duplicates,
        "forbidden_tool_violations": violations,
        "invalid_decisions": len(failed) + sum(e.code == "INVALID_DECISION" for e in state.errors),
        "decision_attempts": len(attempts) or state.iteration_count,
        "model_decision_attempts": sum(e["event"] != "LLM_FAILED" for e in attempts)
        if attempts
        else state.iteration_count,
        "duplicate_tool_calls": duplicates,
        "tool_attempts": calls + len(failed),
        "abstention_correct": status_correct and abstentions_correct
        if "ABSTAIN" in case["expected_status"] or case.get("expected_abstention")
        else None,
        "clarification_correct": status_correct if "CLARIFY" in case["expected_status"] else None,
        "max_steps_exceeded": "Límite de pasos alcanzado" in state.missing_information,
        "steps": state.iteration_count,
        "latency_ms": latency,
        "provider_errors": sum(e["event"] == "LLM_FAILED" for e in attempts),
        "input_tokens": tokens("prompt_tokens"),
        "output_tokens": tokens("completion_tokens"),
        "total_tokens": tokens("total_tokens"),
        "reasoning_tokens": tokens("reasoning_tokens"),
        "usage_complete": bool(attempts)
        and all(
            e.get("usage") and "prompt_tokens" in e["usage"] and "completion_tokens" in e["usage"]
            for e in attempts
        ),
    }
    row["result"] = classify_result(result, attempts, row["task_success"])
    row["provider_error"] = provider_failure_details(attempts) if row["provider_errors"] else None
    if row["result"] in ("PROVIDER_ERROR", "NOT_EVALUATED"):
        # Missing expected tools after an interrupted run are not model mistakes.
        for key in ("task_success", "tools_correct", "abstention_correct", "clarification_correct"):
            row[key] = None
    return row


def aggregate(rows, settings):
    evaluated = [r for r in rows if r["result"] in ("PASS", "FAIL")]

    def mean(key, population=rows):
        values = [r[key] for r in population if r[key] is not None]
        return sum(values) / len(values) if values else None

    def total(key, population=rows):
        return sum(r[key] for r in population)

    def quality_rate(numerator, denominator):
        count = total(denominator, evaluated)
        return total(numerator, evaluated) / count if count else None

    totals = {
        k: sum(r[k] for r in rows if r[k] is not None)
        if any(r[k] is not None for r in rows)
        else None
        for k in ("input_tokens", "output_tokens", "total_tokens", "reasoning_tokens")
    }
    cost = None
    if (
        rows
        and all(r["usage_complete"] for r in rows)
        and settings.llm_input_price_per_1m is not None
        and settings.llm_output_price_per_1m is not None
        and not totals["reasoning_tokens"]
    ):
        cost = (
            totals["input_tokens"] * settings.llm_input_price_per_1m
            + totals["output_tokens"] * settings.llm_output_price_per_1m
        ) / 1_000_000
    return {
        "case_count": len({r["id"] for r in rows}),
        "run_count": len(rows),
        "total_cases": len(rows),
        "evaluated_cases": len(evaluated),
        "passed_cases": sum(r["result"] == "PASS" for r in rows),
        "failed_cases": sum(r["result"] == "FAIL" for r in rows),
        "provider_error_cases": sum(r["result"] == "PROVIDER_ERROR" for r in rows),
        "not_evaluated_cases": sum(r["result"] == "NOT_EVALUATED" for r in rows),
        "provider_error_rate": sum(r["result"] == "PROVIDER_ERROR" for r in rows) / len(rows)
        if rows
        else None,
        "task_success_rate": mean("task_success", evaluated),
        "tool_selection_accuracy": mean("tools_correct", evaluated),
        "forbidden_tool_violations": total("forbidden_tool_violations", evaluated),
        "invalid_decision_rate": quality_rate("invalid_decisions", "model_decision_attempts"),
        "duplicate_tool_call_rate": quality_rate("duplicate_tool_calls", "tool_attempts"),
        "observed_forbidden_tool_violations": total("forbidden_tool_violations"),
        "observed_invalid_decisions": total("invalid_decisions"),
        "observed_duplicate_tool_calls": total("duplicate_tool_calls"),
        "abstention_correctness": mean("abstention_correct", evaluated),
        "clarification_correctness": mean("clarification_correct", evaluated),
        "max_steps_exceeded": total("max_steps_exceeded"),
        "average_steps": mean("steps", evaluated),
        "average_latency": mean("latency_ms", evaluated),
        "attempted_average_steps": mean("steps"),
        "attempted_average_latency": mean("latency_ms"),
        "provider_errors": total("provider_errors"),
        **totals,
        "cost": cost,
    }


def evaluate(
    settings,
    *,
    runs=1,
    fake=False,
    cases=None,
    output_dir=None,
    delay_seconds=0,
    provider_error_cooldown_seconds=0,
    llm_min_interval_seconds=0,
):
    if runs < 1:
        raise ValueError("runs must be positive")
    for delay in (delay_seconds, provider_error_cooldown_seconds, llm_min_interval_seconds):
        if not math.isfinite(delay) or delay < 0:
            raise ValueError("Delays must be finite and nonnegative")
    if not fake and settings.llm_provider not in ("compatible", "gemini"):
        raise ValueError("Select a real provider, or explicitly request fake=True")
    instructions = get_system_instructions(settings.agent_prompt_version)
    cases = load_cases() if cases is None else cases
    output = Path(output_dir or ROOT / "evals/results")
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    delay_seconds = 0 if fake else delay_seconds
    provider_error_cooldown_seconds = 0 if fake else provider_error_cooldown_seconds
    llm_min_interval_seconds = 0 if fake else llm_min_interval_seconds
    # A decide wrapper would miss provider-internal retries. Every external attempt
    # uses this dedicated client; fixture tools use their own unthrottled client.
    hooks = (
        {"request": [SequentialLLMRateLimiter(llm_min_interval_seconds)]}
        if (llm_min_interval_seconds)
        else {}
    )
    with httpx.Client(event_hooks=hooks) as llm_http:
        provider = FakeLLMProvider() if fake else build_provider(settings, llm_http)
        for case in cases:
            for run in range(1, runs + 1):
                wait_seconds = 0
                if rows and not fake:
                    previous = rows[-1]
                    details = previous["provider_error"]
                    rate_limited = (
                        previous["result"] == "PROVIDER_ERROR"
                        and details
                        and (
                            details["http_statuses"][-1] == 429
                            or details["codes"][-1] == "RESOURCE_EXHAUSTED"
                        )
                    )
                    wait_seconds = max(
                        delay_seconds, provider_error_cooldown_seconds if rate_limited else 0
                    )
                    if wait_seconds:
                        print(
                            f"Waiting {wait_seconds:g}s before {case['id']} run={run}", flush=True
                        )
                        sleep(wait_seconds)
                with httpx.Client(transport=fixture_transport(case)) as data_http:
                    repo = RecordingRepository(str(output / "traces.sqlite3"))
                    registry = build_registry(
                        ArgentinaMarketTrackerClient(data_http, "https://market.test"),
                        BolsarClient(data_http, "https://bolsar.test"),
                        LocalMethodologyRetriever(),
                    )
                    agent = EquityAgent(provider, registry, repo, settings.max_agent_steps)
                    started = perf_counter()
                    result = agent.run(case["input"])
                    row = score_case(case, repo.state, result, (perf_counter() - started) * 1000)
                    rows.append({**row, "run": run, "delay_before_run_seconds": wait_seconds})
                    print(
                        f"{case['id']} run={run} result={row['result']} status={result.status} trace={result.trace_id}",
                        flush=True,
                    )
    report = {
        "provider": "fake" if fake else settings.llm_provider,
        "model": None if fake else settings.llm_model,
        "provider_environment": None if fake else provider_environment(settings.llm_base_url),
        "response_format": None if fake else settings.llm_response_format,
        "prompt_version": settings.agent_prompt_version,
        "system_instructions_sha256": None
        if fake
        else hashlib.sha256(instructions.encode("utf-8")).hexdigest(),
        "dataset_version": DATASET_VERSION,
        "timestamp": datetime.now(UTC).isoformat(),
        "data_mode": "fixtures",
        "runs_per_case": runs,
        "evaluator_version": "phase2-v4",
        "delay_seconds": delay_seconds,
        "llm_min_interval_seconds": llm_min_interval_seconds,
        "rate_limit_strategy": "sequential_http_request_start_interval"
        if llm_min_interval_seconds
        else "disabled",
        "provider_error_cooldown_seconds": provider_error_cooldown_seconds,
        "delay_policy": "max(delay_seconds, cooldown_after_terminal_rate_limit)",
        "metrics": aggregate(rows, settings),
        "cases": rows,
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    model = "".join(c if c.isalnum() else "_" for c in settings.llm_model)[:80]
    path = output / (
        "fake_baseline.json"
        if fake
        else f"real_llm_{model}_{settings.agent_prompt_version}_{stamp}.json"
    )
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report, path
