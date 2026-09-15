from pathlib import Path

import httpx
import pytest

from merval_agent.adapters.bolsar import BolsarClient
from merval_agent.adapters.bolsar_parser import parse_documents, select_latest
from merval_agent.adapters.market_tracker import ArgentinaMarketTrackerClient, normalize_history
from merval_agent.domain.errors import ExternalServiceError


def test_normalization(payload):
    history = normalize_history(payload, "GGAL", "6M", "https://test")
    assert history.mode == "live"
    assert len(history.bars) == 60
    assert history.currency == "peso_Argentino"
    payload["meta"]["source"] = "demo"
    assert normalize_history(payload, "GGAL", "6M", "https://test").mode == "demo"


@pytest.mark.parametrize(
    "change",
    [{"ok": False}, {"symbol": "PAMP"}, {"data": [{}]}, {"market": "NYSE"}, {"fetchedAt": "bad"}],
)
def test_invalid_market_contract(payload, change):
    with pytest.raises(ExternalServiceError):
        normalize_history({**payload, **change}, "GGAL", "6M", "https://test")


def test_duplicates_rejected(payload):
    payload["data"].append(payload["data"][0])
    with pytest.raises(ExternalServiceError):
        normalize_history(payload, "GGAL", "6M", "https://test")


def test_market_http(payload):
    def handler(request):
        assert request.url.path == "/api/stocks/GGAL/history"
        assert dict(request.url.params) == {"range": "6M", "market": "bCBA"}
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        assert (
            ArgentinaMarketTrackerClient(http, "https://test").get_history("GGAL", "6M").ticker
            == "GGAL"
        )


@pytest.mark.parametrize("status", [403, 429, 500])
def test_external_status(status):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status))) as http:
        with pytest.raises(ExternalServiceError):
            ArgentinaMarketTrackerClient(http, "https://test").get_history("GGAL", "1M")
        with pytest.raises(ExternalServiceError):
            BolsarClient(http, "https://test").list_documents("PAMP")


def test_bolsar_parser_and_latest():
    html = (Path(__file__).parents[1] / "fixtures/bolsar.html").read_text(encoding="utf-8")
    docs = parse_documents(html)
    assert len(docs) == 3
    assert docs[0].document_type == "SUMMARY"
    assert docs[1].published_at.isoformat() == "2026-08-20"
    assert select_latest(docs).document_id == "102"
    assert select_latest([docs[0]]).document_id == "101"
    assert select_latest([]) is None
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=html))
    ) as http:
        client = BolsarClient(http)
        assert len(client.list_documents("PAMP", 2026, 2)) == 3
        assert client.list_documents("PAMP", 2026, 1) == []
        assert client.find_latest_financial_statement("GGAL") is None
        assert client.find_latest_financial_statement("PAMP").document_id == "102"


def test_html_change_is_not_empty_data():
    with pytest.raises(ExternalServiceError):
        parse_documents("<html>Access denied</html>")


@pytest.mark.parametrize(
    "change",
    [
        {"range": "1W"},
        {"meta": None},
        {"meta": []},
        {"data": None},
        {"meta": {"stale": "false"}},
        {"fetchedAt": "2026-09-15T12:00:00"},
    ],
)
def test_additional_invalid_market_payloads(payload, change):
    with pytest.raises(ExternalServiceError):
        normalize_history({**payload, **change}, "GGAL", "6M", "https://test")


@pytest.mark.parametrize("body", [None, [], "invalid"])
def test_non_object_market_payload(body):
    with pytest.raises(ExternalServiceError):
        normalize_history(body, "GGAL", "6M", "https://test")


@pytest.mark.parametrize("client_class", [ArgentinaMarketTrackerClient, BolsarClient])
def test_timeout_is_sanitized(client_class):
    def timeout(request):
        raise httpx.ReadTimeout("Bearer private-test-value", request=request)

    with httpx.Client(transport=httpx.MockTransport(timeout), timeout=0.1) as http:
        client = client_class(http, "https://test")
        with pytest.raises(ExternalServiceError) as caught:
            if client_class is BolsarClient:
                client.list_documents("PAMP")
            else:
                client.get_history("GGAL", "6M")
        assert "private-test-value" not in str(caught.value)


def test_unknown_source_and_mixed_currency(payload):
    payload["meta"] = {}
    assert normalize_history(payload, "GGAL", "6M", "test").mode == "unknown"
    payload["data"][0]["currency"] = "USD"
    with pytest.raises(ExternalServiceError):
        normalize_history(payload, "GGAL", "6M", "test")


def test_bolsar_spanish_protocol_relative_empty_and_incomplete():
    html = (Path(__file__).parents[1] / "fixtures/bolsar.html").read_text(encoding="utf-8")
    docs = parse_documents(html)
    assert "Síntesis" in docs[0].reference
    assert docs[0].issuer
    assert all(d.source_url.startswith("https://ws.bolsar.info/descarga/?id=") for d in docs)
    assert all(d.fiscal_period is None for d in docs)
    header = "<table><tr><th>Fecha Emisor Especie Referencia</th></tr>"
    assert parse_documents(header + "</table>") == []
    for body in ("", header + "<tr><td>incomplete</td></tr></table>"):
        with pytest.raises(ExternalServiceError):
            parse_documents(body)
