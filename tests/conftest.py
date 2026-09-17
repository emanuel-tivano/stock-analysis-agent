from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from merval_agent.adapters.bolsar import BolsarClient
from merval_agent.adapters.llm.fake import FakeLLMProvider
from merval_agent.adapters.market_tracker import ArgentinaMarketTrackerClient
from merval_agent.agents.equity_agent import EquityAgent
from merval_agent.domain.models import Bar
from merval_agent.retrieval.local import LocalMethodologyRetriever
from merval_agent.tools.registry import build_registry


class MemoryRepository:
    def __init__(self):
        self.records = []

    def save(self, state, result):
        self.records.append((state, result))


@pytest.fixture
def bars():
    return [
        Bar(
            date=date.today() - timedelta(days=59 - i),
            open=100 + i,
            high=102 + i,
            low=99 + i,
            close=101 + i,
            volume=1000 + i,
        )
        for i in range(60)
    ]


@pytest.fixture
def payload(bars):
    return {
        "ok": True,
        "symbol": "GGAL",
        "market": "bCBA",
        "range": "6M",
        "fetchedAt": datetime.now(UTC).isoformat(),
        "meta": {"source": "live", "stale": False},
        "data": [{**b.model_dump(mode="json"), "currency": "peso_Argentino"} for b in bars],
    }


@pytest.fixture
def make_agent(payload):
    clients = []

    def factory(provider=None, market_status=200, data=None, max_steps=12):
        def handler(request):
            if request.url.path.endswith("/quote"):
                return httpx.Response(503, json={"ok": False})
            if "/history" in request.url.path:
                body = dict(payload if data is None else data)
                body["symbol"] = request.url.path.split("/")[-2]
                body["range"] = request.url.params["range"]
                return httpx.Response(market_status, json=body)
            return httpx.Response(
                200,
                text="<table><tr><th>Fecha</th><th>Emisor</th><th>Especie</th><th>Referencias</th><th>Archivo</th></tr></table>",
            )

        http = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(http)
        repo = MemoryRepository()
        registry = build_registry(
            ArgentinaMarketTrackerClient(http, "https://market.test"),
            BolsarClient(http, "https://bolsar.test"),
            LocalMethodologyRetriever(),
        )
        return EquityAgent(provider or FakeLLMProvider(), registry, repo, max_steps), repo

    yield factory
    for client in clients:
        client.close()
