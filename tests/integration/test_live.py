import os

import httpx
import pytest

from merval_agent.adapters.bolsar import BolsarClient
from merval_agent.adapters.market_tracker import ArgentinaMarketTrackerClient
from merval_agent.config import Settings

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


def test_bolsar_live():
    settings = Settings()
    with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True) as http:
        assert isinstance(BolsarClient(http, settings.bolsar_base_url).list_documents("PAMP"), list)
