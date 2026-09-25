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

    def factory(
        provider=None,
        market_status=200,
        data=None,
        max_steps=12,
        clock=None,
        validation_quotes=None,
        validation_status=404,
    ):
        history_requested = set()
        paths = []

        def handler(request):
            paths.append(request.url.path)
            if request.url.path.endswith("/quote"):
                symbol = request.url.path.split("/")[-2]
                if symbol not in history_requested:
                    if validation_quotes and symbol in validation_quotes:
                        return httpx.Response(
                            200,
                            json={
                                "ok": True,
                                "symbol": symbol,
                                "market": "bCBA",
                                "source": "live",
                                "stale": False,
                                "data": {
                                    "symbol": symbol,
                                    "market": "bCBA",
                                    "description": validation_quotes[symbol],
                                    "timestamp": datetime.now(UTC).isoformat(),
                                    "price": 160,
                                    "open": 159,
                                    "high": 161,
                                    "low": 158,
                                    "volume": 1000,
                                    "currency": "peso_Argentino",
                                },
                            },
                        )
                    return httpx.Response(
                        validation_status,
                        json={
                            "ok": False,
                            "error": "QUOTE_NOT_FOUND"
                            if validation_status == 404
                            else "QUOTE_ERROR",
                        },
                    )
                return httpx.Response(503, json={"ok": False})
            if "/history" in request.url.path:
                body = dict(payload if data is None else data)
                symbol = request.url.path.split("/")[-2]
                history_requested.add(symbol)
                body["symbol"] = symbol
                body["range"] = request.url.params["range"]
                return httpx.Response(market_status, json=body)
            return httpx.Response(
                200,
                text="<table><tr><th>Fecha</th><th>Emisor</th><th>Especie</th><th>Referencias</th><th>Archivo</th></tr></table>",
            )

        http = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(http)
        repo = MemoryRepository()
        repo.market_paths = paths
        market_options = {"clock": clock} if clock is not None else {}
        registry = build_registry(
            ArgentinaMarketTrackerClient(http, "https://market.test", **market_options),
            BolsarClient(http, "https://bolsar.test"),
            LocalMethodologyRetriever(),
        )
        return EquityAgent(
            provider or FakeLLMProvider(), registry, repo, max_steps, clock=clock
        ), repo

    yield factory
    for client in clients:
        client.close()
