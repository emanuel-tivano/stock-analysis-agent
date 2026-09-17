from copy import deepcopy
from datetime import date, timedelta

import pytest

from merval_agent.adapters.market_tracker import normalize_history
from merval_agent.domain.errors import ExternalServiceError


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
    history = normalize_history(bma_payload, "BMA", "6M", "test")
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
    history = normalize_history(payload, "GGAL", "6M", "test")
    assert [b.date.isoformat() for b in history.bars] == [r["date"] for r in valid]


@pytest.mark.parametrize("empty", [False, True])
def test_no_valid_bars_is_external_invalid_response(bma_payload, empty):
    bma_payload["data"] = [] if empty else bma_payload["data"][-2:]
    with pytest.raises(ExternalServiceError, match="Invalid Market Tracker response"):
        normalize_history(bma_payload, "BMA", "6M", "test")


def test_partial_history_tool_succeeds(make_agent, bma_payload):
    agent, repo = make_agent(data=bma_payload)
    agent.run("Analizá técnicamente BMA")
    state = repo.records[0][0]
    observations = [o for o in state.observations if o.tool_name == "get_market_history"]
    assert len(observations) == 1
    assert observations[0].success
    assert len(state.technical_data.bars) == 122


def test_http_error_remains_external_service(make_agent):
    agent, repo = make_agent(market_status=503)
    agent.run("Analizá técnicamente BMA")
    observations = [
        o for o in repo.records[0][0].observations if o.tool_name == "get_market_history"
    ]
    assert observations
    assert all(not o.success and o.error.code == "EXTERNAL_SERVICE" for o in observations)
