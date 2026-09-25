import os

import httpx
import pytest

from merval_agent.adapters.bolsar import BolsarClient
from merval_agent.adapters.market_tracker import ArgentinaMarketTrackerClient
from merval_agent.config import Settings
from merval_agent.domain.models import now
from merval_agent.domain.policy import MAX_PROVIDER_CLOCK_AHEAD
from merval_agent.domain.technical import calculate
from merval_agent.domain.technical_assessment import assess

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE_TESTS") != "1", reason="Explicit RUN_LIVE_TESTS=1 required"
    ),
]


def test_market_live():
    settings = Settings()
    with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True) as http:
        history = ArgentinaMarketTrackerClient(http, settings.market_tracker_base_url).get_history(
            "GGAL", "1M"
        )
        assert history.ticker == "GGAL"


@pytest.mark.parametrize("ticker", ["TECO2", "TGNO4", "TGSU2", "A3"])
def test_domestic_numeric_suffix_tickers_live(ticker):
    settings = Settings()
    with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True) as http:
        client = ArgentinaMarketTrackerClient(http, settings.market_tracker_base_url)
        validation = client.validate_instrument(ticker)

    assert validation.status == "VALIDATED"
    assert validation.ticker == ticker
    assert validation.classification == "DOMESTIC_EQUITY_CANDIDATE"


@pytest.mark.parametrize("ticker,expected", [("GGAL", "COMPLETE"), ("TECO2", "PARTIAL")])
def test_repeated_live_assessment_is_stable_across_small_remote_clock_skew(ticker, expected):
    settings = Settings()
    statuses = []
    with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True) as http:
        client = ArgentinaMarketTrackerClient(http, settings.market_tracker_base_url)
        for _ in range(3):
            history = client.get_history(ticker, "6M")
            evaluated_at = now()
            assessment = assess(history, calculate(history.bars), evaluated_at)
            assert history.received_at <= evaluated_at
            assert history.provider_fetched_at - history.received_at <= MAX_PROVIDER_CLOCK_AHEAD
            statuses.append(assessment.status)

    assert statuses == [expected] * 3


def test_bolsar_live():
    settings = Settings()
    with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True) as http:
        assert isinstance(BolsarClient(http, settings.bolsar_base_url).list_documents("PAMP"), list)
