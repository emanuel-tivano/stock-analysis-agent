from copy import deepcopy
from datetime import UTC, date, datetime, timedelta

import pytest

from merval_agent.adapters.market_tracker import normalize_history
from merval_agent.agents.report import build_report
from merval_agent.domain.errors import ExternalServiceError
from merval_agent.domain.models import (
    AgentState,
    AssetResolution,
    Bar,
    QuoteSnapshot,
    UserIntent,
)
from merval_agent.domain.technical import calculate
from merval_agent.domain.technical_assessment import assess
from merval_agent.presentation.presenter import present_analysis

RECEIVED_AT = datetime(2026, 9, 16, 12, tzinfo=UTC)


@pytest.fixture
def bma_payload(payload):
    payload["symbol"] = "BMA"
    template = payload["data"][0]
    payload["data"] = [
        {**template, "date": (date(2026, 6, 1) + timedelta(days=i)).isoformat()} for i in range(122)
    ]
    payload["data"] += [
        {
            **template,
            "date": "2026-04-10",
            "open": 12020,
            "high": 12250,
            "low": 11770,
            "close": 11750,
        },
        {
            **template,
            "date": "2026-05-19",
            "open": 10990,
            "high": 10990,
            "low": 10200,
            "close": 10160,
        },
    ]
    payload["totalPoints"] = 124
    return payload


def test_bma_partial_history_preserves_valid_bars_and_input(bma_payload, caplog):
    original = deepcopy(bma_payload)
    history = normalize_history(bma_payload, "BMA", "6M", "test", received_at=RECEIVED_AT)
    assert len(history.bars) == 122
    assert [b.model_dump(mode="json") for b in history.bars] == [
        {k: v for k, v in row.items() if k != "currency"} for row in original["data"][:122]
    ]
    assert bma_payload == original  # Includes the two defective OHLC values.
    record = caplog.records[-1]
    assert record.discarded_rows == 2
    assert record.valid_rows == 122


@pytest.mark.parametrize("invalid", [{}, None, [], "bad", {"date": "bad"}])
def test_malformed_row_does_not_hide_short_valid_history(payload, invalid):
    valid = payload["data"][:2]
    payload["data"] = [valid[1], invalid, valid[0]]
    history = normalize_history(payload, "GGAL", "6M", "test", received_at=RECEIVED_AT)
    assert [b.date.isoformat() for b in history.bars] == [r["date"] for r in valid]


@pytest.mark.parametrize("empty", [False, True])
def test_no_valid_bars_is_external_invalid_response(bma_payload, empty):
    bma_payload["data"] = [] if empty else bma_payload["data"][-2:]
    with pytest.raises(ExternalServiceError, match="Invalid Market Tracker response"):
        normalize_history(bma_payload, "BMA", "6M", "test", received_at=RECEIVED_AT)


def test_partial_history_tool_succeeds(make_agent, bma_payload):
    agent, repo = make_agent(data=bma_payload)
    agent.run("Analizá técnicamente BMA")
    state = repo.records[0][0]
    observations = [o for o in state.observations if o.tool_name == "get_market_history"]
    assert len(observations) == 1
    assert observations[0].success
    assert len(state.technical_data.bars) == 122


def _real_case_payload(ticker: str):
    start = date(2026, 4, 8)
    rows = [
        {
            "date": (start + timedelta(days=index)).isoformat(),
            "timestamp": f"{(start + timedelta(days=index)).isoformat()}T16:56:20.000",
            "open": 3000 + index,
            "high": 3010 + index,
            "low": 2990 + index,
            "close": 3005 + index,
            "volume": 100_000 + index,
            "currency": "peso_Argentino",
        }
        for index in range(126)
    ]
    return {
        "ok": True,
        "symbol": ticker,
        "market": "bCBA",
        "range": "6M",
        "fetchedAt": "2026-08-12T20:00:00.095820Z",
        "meta": {"source": "live", "stale": False},
        "data": rows,
    }


def _append_quote(history):
    received_at = datetime(2026, 8, 12, 20, tzinfo=UTC)
    quote_bar = Bar(
        date=date(2026, 8, 12),
        open=3200,
        high=3220,
        low=3190,
        close=3210,
        volume=150_000,
    )
    quote = QuoteSnapshot(
        bar=quote_bar,
        source="fixture://quote",
        observed_at=received_at,
        provider_fetched_at=received_at + timedelta(seconds=1, microseconds=112_547),
        received_at=received_at,
        currency="peso_Argentino",
    )
    return history.model_copy(
        update={
            "bars": [*history.bars, quote_bar],
            "quote": quote,
            "enrichment_status": "appended",
        }
    )


def test_teco2_real_126_rows_discard_two_and_remain_answerable():
    payload = _real_case_payload("TECO2")
    payload["data"][27].update(
        timestamp="2026-05-05T16:56:22.317",
        open=3552.5,
        high=3625,
        low=3447.5,
        close=3445,
        volume=159084,
    )
    payload["data"][30].update(
        timestamp="2026-05-08T16:56:20.733",
        open=3540,
        high=3645,
        low=3500,
        close=3490,
        volume=131953,
    )
    received_at = datetime(2026, 8, 12, 20, tzinfo=UTC)
    history = normalize_history(payload, "TECO2", "6M", "fixture://teco2", received_at=received_at)
    history = _append_quote(history)
    assessment = assess(history, calculate(history.bars), received_at)

    assert history.discarded_rows == 2
    assert len(history.bars) == 125
    assert len({bar.date for bar in history.bars}) == 125
    assert assessment.status == "PARTIAL"
    assert assessment.confidence == "MEDIUM"
    assert assessment.trend != "UNAVAILABLE"
    assert assessment.momentum != "UNAVAILABLE"


def test_ggal_same_quality_without_discards_is_complete():
    received_at = datetime(2026, 8, 12, 20, tzinfo=UTC)
    history = normalize_history(
        _real_case_payload("GGAL"),
        "GGAL",
        "6M",
        "fixture://ggal",
        received_at=received_at,
    )
    history = _append_quote(history)
    assessment = assess(history, calculate(history.bars), received_at)

    assert history.discarded_rows == 0
    assert len(history.bars) == 127
    assert assessment.status == "COMPLETE"


def test_teco2_presenter_does_not_report_invalid_data_for_accepted_skew():
    payload = _real_case_payload("TECO2")
    payload["data"][27]["close"] = payload["data"][27]["low"] - 1
    payload["data"][30]["close"] = payload["data"][30]["low"] - 1
    evaluated_at = datetime(2026, 8, 12, 20, tzinfo=UTC)
    history = _append_quote(
        normalize_history(
            payload,
            "TECO2",
            "6M",
            "fixture://teco2",
            received_at=evaluated_at,
        )
    )
    report = build_report(
        AgentState(
            user_request="Técnico TECO2",
            status="ANSWER",
            intent=UserIntent(analysis_type="technical"),
            resolved_asset=AssetResolution(ticker="TECO2", confidence=1),
            technical_data=history,
            technical_metrics=calculate(history.bars),
        ),
        "",
        "",
        7,
        reference_time=evaluated_at,
    )
    presented = present_analysis(report)

    assert report.technical.assessment.status == "PARTIAL"
    assert not any(
        "Datos inválidos: no fue posible validar una lectura técnica" in warning
        for warning in presented.warnings
    )


def test_http_error_remains_external_service(make_agent):
    agent, repo = make_agent(market_status=503)
    agent.run("Analizá técnicamente BMA")
    observations = [
        o for o in repo.records[0][0].observations if o.tool_name == "get_market_history"
    ]
    assert observations
    assert all(not o.success and o.error.code == "EXTERNAL_SERVICE" for o in observations)
