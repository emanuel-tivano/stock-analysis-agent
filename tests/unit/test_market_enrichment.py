from copy import deepcopy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError

from merval_agent.adapters.market_tracker import ArgentinaMarketTrackerClient
from merval_agent.agents.report import build_report
from merval_agent.domain.errors import ExternalServiceError
from merval_agent.domain.models import AgentState, AssetResolution, Bar, MarketHistory, UserIntent
from merval_agent.domain.technical import calculate

CLOCK = datetime(2026, 9, 16, 22, tzinfo=UTC)


@pytest.fixture
def history_payload():
    return {
        "ok": True,
        "symbol": "GGAL",
        "market": "bCBA",
        "range": "6M",
        "fetchedAt": "2026-09-16T12:00:00Z",
        "meta": {"source": "live", "stale": False},
        "data": [
            {
                "date": (CLOCK.date() - timedelta(days=20 - i)).isoformat(),
                "open": 100 + i,
                "high": 105 + i,
                "low": 99 + i,
                "close": 102 + i,
                "volume": 1000,
                "currency": "peso_Argentino",
            }
            for i in range(20)
        ],
    }


@pytest.fixture
def quote_payload():
    return {
        "ok": True,
        "symbol": "GGAL",
        "market": "bCBA",
        "source": "live",
        "stale": False,
        "data": {
            "timestamp": "2026-09-16T16:59:51-03:00",
            "open": 120,
            "high": 130,
            "low": 119,
            "price": 125,
            "volume": None,
            "currency": "peso_Argentino",
        },
    }


def fetch(history, quote, *, status=200, enrich=True):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/history"):
            return httpx.Response(200, json=history)
        assert request.url.path == "/api/stocks/GGAL/quote"
        assert dict(request.url.params) == {"market": "bCBA"}
        if isinstance(quote, Exception):
            raise quote
        return httpx.Response(status, json=quote)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        result = ArgentinaMarketTrackerClient(
            http, "https://market.test", clock=lambda: CLOCK, enrich_quote=enrich
        ).get_history("GGAL", "6M")
    return result, paths


def test_new_quote_provisional_provenance_and_metrics(history_payload, quote_payload):
    original = deepcopy(history_payload)
    history, paths = fetch(history_payload, quote_payload)
    assert len(paths) == 2
    assert history_payload == original
    assert history.enrichment_status == "appended"
    assert history.quote.provisional and history.quote.mode == "live"
    assert history.quote.fetched_at == CLOCK
    assert history.fetched_at == datetime(2026, 9, 16, 12, tzinfo=UTC)
    assert "/quote?" in history.quote.source and "/history?" in history.source
    assert history.bars[-1].volume is None
    assert history.bars[-1].date == CLOCK.date()
    assert [b.date for b in history.bars] == sorted({b.date for b in history.bars})
    assert MarketHistory.model_validate_json(history.model_dump_json()) == history
    metrics = calculate(history.bars)
    assert metrics.sample_size == 21 and metrics.average_volume is None
    assert metrics.change_percent == pytest.approx((125 / 102 - 1) * 100)
    assert metrics.period_high == 130 and metrics.period_low == 99
    assert metrics.sma20 is not None and metrics.rsi14 is not None


@pytest.mark.parametrize("timestamp", ["2026-09-15T18:00:00Z", "2026-09-14T18:00:00Z"])
def test_same_or_older_quote_not_appended(history_payload, quote_payload, timestamp):
    quote_payload["data"]["timestamp"] = timestamp
    history, paths = fetch(history_payload, quote_payload)
    assert len(paths) == 2 and len(history.bars) == 20
    assert history.quote is None and history.enrichment_status == "not_newer"


@pytest.mark.parametrize("status", [400, 401, 429, 500, 503])
def test_quote_http_failure_is_best_effort_once(history_payload, quote_payload, status):
    history, paths = fetch(history_payload, quote_payload, status=status)
    assert len(paths) == 2 and len(history.bars) == 20
    assert history.enrichment_status == "unavailable" and history.quote is None


@pytest.mark.parametrize("bad", [None, [], {}, "bad", httpx.ReadTimeout("private")])
def test_invalid_quote_or_timeout_preserves_history(history_payload, bad):
    history, paths = fetch(history_payload, bad)
    assert len(paths) == 2 and len(history.bars) == 20 and history.quote is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("stale", True),
        ("stale", "false"),
        ("stale", None),
        ("source", "demo"),
        ("source", "unknown"),
        ("symbol", "BMA"),
        ("market", "NYSE"),
    ],
)
def test_quote_identity_and_quality_rejected(history_payload, quote_payload, field, value):
    quote_payload[field] = value
    history, _ = fetch(history_payload, quote_payload)
    assert len(history.bars) == 20 and history.enrichment_status == "unavailable"


@pytest.mark.parametrize(
    "field,value",
    [
        ("high", 121),
        ("low", 126),
        ("price", -1),
        ("volume", -1),
        ("currency", "USD"),
        ("currency", None),
        ("timestamp", "2026-09-16garbage"),
        ("timestamp", "2026-09-16T12:00:00"),
        ("timestamp", "2026-09-17T18:00:00Z"),
        ("timestamp", "2026-09-16T23:00:00Z"),
        ("timestamp", "2026-09-01T18:00:00Z"),
        ("timestamp", "1790000000"),
    ],
)
def test_bad_quote_values_rejected(history_payload, quote_payload, field, value):
    quote_payload["data"][field] = value
    history, _ = fetch(history_payload, quote_payload)
    assert len(history.bars) == 20 and history.quote is None


def test_timezone_uses_market_date_not_iso_prefix(history_payload, quote_payload):
    quote_payload["data"]["timestamp"] = "2026-09-16T01:30:00Z"
    history, _ = fetch(history_payload, quote_payload)
    assert history.enrichment_status == "not_newer"  # September 15 in Buenos Aires.


@pytest.mark.parametrize("volume,average", [(None, None), (0, 20000 / 21), (1000, 1000)])
def test_missing_volume_distinct_from_zero(history_payload, quote_payload, volume, average):
    quote_payload["data"]["volume"] = volume
    quote_payload["data"]["amountTraded"] = 99999999
    history, _ = fetch(history_payload, quote_payload)
    metrics = calculate(history.bars)
    assert metrics.average_volume == average
    assert history.bars[-1].volume == volume


@pytest.mark.parametrize("rows", [[], [{}]])
def test_invalid_history_is_error_before_quote(history_payload, quote_payload, rows):
    history_payload["data"] = rows
    with pytest.raises(ExternalServiceError):
        fetch(history_payload, quote_payload)


def test_history_duplicates_remain_error(history_payload, quote_payload):
    history_payload["data"].append(history_payload["data"][0])
    with pytest.raises(ExternalServiceError):
        fetch(history_payload, quote_payload)


@pytest.mark.parametrize("mode,stale", [("live", True), ("demo", False), ("unknown", False)])
def test_quote_cannot_launder_history_quality(history_payload, quote_payload, mode, stale):
    history_payload["meta"] = {"source": mode, "stale": stale}
    history, paths = fetch(history_payload, quote_payload)
    assert len(paths) == 1 and history.enrichment_status == "ineligible_history"
    assert history.stale == stale and history.mode == mode


def test_old_history_and_disabled_enrichment_make_one_request(history_payload, quote_payload):
    history, paths = fetch(history_payload, quote_payload, enrich=False)
    assert len(paths) == 1 and history.enrichment_status == "not_requested"
    history_payload["data"] = history_payload["data"][:2]
    history, paths = fetch(history_payload, quote_payload)
    assert len(paths) == 1 and history.enrichment_status == "ineligible_history"


def test_partial_rows_visible_in_report_and_quote_evidence(history_payload, quote_payload):
    history_payload["data"].append({"bad": "row"})
    history, _ = fetch(history_payload, quote_payload)
    state = AgentState(
        user_request="Tecnico GGAL",
        status="ANSWER",
        intent=UserIntent(analysis_type="technical"),
        resolved_asset=AssetResolution(ticker="GGAL", confidence=1),
        technical_data=history,
        technical_metrics=calculate(history.bars),
    )
    result = build_report(state, "Data", "Calculated", 7, reference_time=CLOCK)
    assert result.status == "ANSWER" and result.as_of == CLOCK.date()
    assert not result.data_quality.stale_data
    assert set(result.sources) == {history.source, history.quote.source}
    assert result.technical.evidence[0].metadata["discarded_rows"] == 1
    assert result.technical.evidence[1].metadata["provisional"]
    assert any("Volumen desconocido" in s for s in result.technical.limitations)
    assert any("provisional" in s for s in result.technical.limitations)
    # A deliberate later evaluation still uses the historical base for freshness.
    assert build_report(
        state, "Data", "Calculated", 7, reference_time=CLOCK + timedelta(days=7)
    ).data_quality.stale_data


def test_null_volume_is_explicit_but_invalid_prices_still_rejected(history_payload):
    data = {k: v for k, v in history_payload["data"][0].items() if k != "currency"}
    assert Bar(**{**data, "volume": None}).volume is None
    for update in ({"volume": -1}, {"volume": float("nan")}, {"high": 1}):
        with pytest.raises(ValidationError):
            Bar(**{**data, **update})


def test_snapshot_provenance_cannot_be_removed_or_mismatched(history_payload, quote_payload):
    history, _ = fetch(history_payload, quote_payload)
    data = history.model_dump()
    for update in ({"quote": None}, {"currency": "USD"}, {"enrichment_status": "not_requested"}):
        with pytest.raises(ValidationError):
            MarketHistory.model_validate({**data, **update})


def test_market_midnight_and_weekend_do_not_imply_closed_session(history_payload, quote_payload):
    history, _ = fetch(history_payload, quote_payload)
    state = AgentState(
        user_request="Tecnico GGAL",
        status="ANSWER",
        intent=UserIntent(analysis_type="technical"),
        technical_data=history,
        technical_metrics=calculate(history.bars),
        resolved_asset=AssetResolution(ticker="GGAL", confidence=1),
    )
    # Saturday: recent Wednesday snapshot remains provisional, no invented close/holiday calendar.
    result = build_report(state, "Data", "Calculated", 7, reference_time=CLOCK + timedelta(days=3))
    assert result.status == "ANSWER" and not result.data_quality.stale_data
    assert result.technical.evidence[-1].metadata["provisional"]
    # UTC changed date, Buenos Aires has not: one calendar day since historical base.
    assert not build_report(
        state,
        "Data",
        "Calculated",
        1,
        reference_time=datetime(2026, 9, 17, 1, tzinfo=UTC),
    ).data_quality.stale_data


def test_invalid_history_never_requests_quote(history_payload):
    history_payload["data"] = []
    requests = []

    def handler(request):
        requests.append(request.url.path)
        assert request.url.path.endswith("/history")
        return httpx.Response(200, json=history_payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ExternalServiceError):
            ArgentinaMarketTrackerClient(
                http, "https://market.test", clock=lambda: CLOCK
            ).get_history("GGAL", "6M")
    assert len(requests) == 1


def test_provisional_snapshot_survives_api_and_trace(
    history_payload, quote_payload, make_agent, tmp_path
):
    from fastapi.testclient import TestClient

    from merval_agent.api.app import create_app
    from merval_agent.config import Settings
    from merval_agent.memory.sqlite import SQLiteRepository

    history, _ = fetch(history_payload, quote_payload)
    agent, _ = make_agent(clock=lambda: CLOCK)
    agent.tools.tools["get_market_history"].handler = lambda a, s: history.model_dump(mode="json")
    agent.repository = SQLiteRepository(str(tmp_path / "snapshot.sqlite3"))
    with TestClient(create_app(agent=agent, settings=Settings(_env_file=None))) as client:
        response = client.post("/agent/run", json={"message": "Tecnico GGAL"})
    body = response.json()
    assert response.status_code == 200 and body["status"] == "ANSWER"
    assert body["as_of"] == "2026-09-16"
    assert body["technical"]["metrics"]["average_volume"] is None
    assert body["technical"]["metrics"]["sample_size"] == 21
    evidence = next(e for e in body["technical"]["evidence"] if e["chunk_id"].endswith(":quote"))
    assert evidence["metadata"]["provisional"]
    trace = agent.repository.get_trace(body["trace_id"])
    snapshot = next(e["market_data"] for e in trace["events"] if "market_data" in e)
    assert snapshot["provisional"] and snapshot["enrichment_status"] == "appended"
    assert snapshot["quote_fetched_at"] == CLOCK.isoformat()
    final_decision = next(
        e
        for e in trace["events"]
        if e["event"] == "DECISION_MADE" and e["action"] == "FINAL_ANSWER"
    )
    assert final_decision["evaluated_at"] == CLOCK.isoformat()


def test_quote_after_snapshot_evaluation_remains_invalid(
    history_payload, quote_payload, make_agent
):
    history, _ = fetch(history_payload, quote_payload)
    future = CLOCK + timedelta(seconds=1)
    quote = history.quote.model_copy(update={"observed_at": future, "fetched_at": future})
    history = history.model_copy(update={"quote": quote})
    agent, repo = make_agent(clock=lambda: CLOCK)
    agent.tools.tools["get_market_history"].handler = lambda a, s: history.model_dump(mode="json")

    result = agent.run("Tecnico GGAL")

    assert result.status == "ABSTAIN"
    assert result.technical.assessment.status == "INVALID_DATA"
    assert result.technical.assessment.freshness == "INVALID"
    final_decision = next(
        e
        for e in repo.records[0][0].trace_events
        if e["event"] == "DECISION_MADE" and e["action"] == "ABSTAIN"
    )
    assert final_decision["evaluated_at"] == CLOCK.isoformat()


def test_one_reference_is_reused_by_decision_and_report(history_payload, quote_payload, make_agent):
    history, _ = fetch(history_payload, quote_payload)
    references = iter(CLOCK + timedelta(seconds=i) for i in (1, 2, 3))
    clock_calls = []

    def clock():
        value = next(references)
        clock_calls.append(value)
        return value

    agent, repo = make_agent(clock=clock)
    agent.tools.tools["get_market_history"].handler = lambda a, s: history.model_dump(mode="json")

    result = agent.run("Tecnico GGAL")
    state = repo.records[0][0]

    assert result.status == "ANSWER"
    assert clock_calls == [
        CLOCK + timedelta(seconds=1),
        CLOCK + timedelta(seconds=2),
        CLOCK + timedelta(seconds=3),
    ]
    assert state.technical_evaluated_at == clock_calls[-1]
    assert result.technical.assessment == state.technical_assessment
    final_decision = next(
        e
        for e in state.trace_events
        if e["event"] == "DECISION_MADE" and e["action"] == "FINAL_ANSWER"
    )
    assert final_decision["evaluated_at"] == clock_calls[-1].isoformat()


def test_default_agent_clock_runs_after_acquisition(make_agent):
    agent, repo = make_agent()

    result = agent.run("Tecnico GGAL")
    state = repo.records[0][0]

    assert result.status == "ANSWER"
    assert state.technical_evaluated_at.tzinfo is not None
    assert state.technical_evaluated_at >= state.technical_data.fetched_at
