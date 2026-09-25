from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from merval_agent.adapters.bolsar import BolsarClient
from merval_agent.adapters.bolsar_parser import parse_documents, select_latest
from merval_agent.adapters.market_tracker import ArgentinaMarketTrackerClient, normalize_history
from merval_agent.domain.errors import ExternalServiceError

RECEIVED_AT = datetime(2026, 9, 16, 12, tzinfo=UTC)


def test_normalization(payload):
    history = normalize_history(payload, "GGAL", "6M", "https://test", received_at=RECEIVED_AT)
    assert history.mode == "live"
    assert len(history.bars) == 60
    assert history.currency == "peso_Argentino"
    assert history.provider_fetched_at == datetime.fromisoformat(payload["fetchedAt"])
    assert history.received_at == RECEIVED_AT
    payload["meta"]["source"] = "demo"
    assert (
        normalize_history(payload, "GGAL", "6M", "https://test", received_at=RECEIVED_AT).mode
        == "demo"
    )


@pytest.mark.parametrize(
    "change",
    [{"ok": False}, {"symbol": "PAMP"}, {"data": [{}]}, {"market": "NYSE"}, {"fetchedAt": "bad"}],
)
def test_invalid_market_contract(payload, change):
    with pytest.raises(ExternalServiceError):
        normalize_history(
            {**payload, **change},
            "GGAL",
            "6M",
            "https://test",
            received_at=RECEIVED_AT,
        )


def test_duplicates_rejected(payload):
    payload["data"].append(payload["data"][0])
    with pytest.raises(ExternalServiceError):
        normalize_history(payload, "GGAL", "6M", "https://test", received_at=RECEIVED_AT)


def test_history_local_receipt_requires_timezone(payload):
    with pytest.raises(ExternalServiceError):
        normalize_history(
            payload,
            "GGAL",
            "6M",
            "https://test",
            received_at=datetime(2026, 9, 16, 12),
        )


def test_market_http(payload):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path == "/api/stocks/GGAL/quote":
            assert dict(request.url.params) == {"market": "bCBA"}
            return httpx.Response(503)
        assert request.url.path == "/api/stocks/GGAL/history"
        assert dict(request.url.params) == {"range": "6M", "market": "bCBA"}
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        assert (
            ArgentinaMarketTrackerClient(http, "https://test").get_history("GGAL", "6M").ticker
            == "GGAL"
        )
    assert paths == ["/api/stocks/GGAL/history", "/api/stocks/GGAL/quote"]


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
        normalize_history(
            {**payload, **change},
            "GGAL",
            "6M",
            "https://test",
            received_at=RECEIVED_AT,
        )


@pytest.mark.parametrize("body", [None, [], "invalid"])
def test_non_object_market_payload(body):
    with pytest.raises(ExternalServiceError):
        normalize_history(body, "GGAL", "6M", "https://test", received_at=RECEIVED_AT)


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
    assert (
        normalize_history(payload, "GGAL", "6M", "test", received_at=RECEIVED_AT).mode == "unknown"
    )
    payload["data"][0]["currency"] = "USD"
    with pytest.raises(ExternalServiceError):
        normalize_history(payload, "GGAL", "6M", "test", received_at=RECEIVED_AT)


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


def _validation_quote(symbol="EDN", market="bCBA", description="Edenor"):
    return {
        "ok": True,
        "symbol": symbol,
        "market": market,
        "source": "live",
        "stale": False,
        "data": {
            "symbol": symbol,
            "market": market,
            "description": description,
            "timestamp": datetime.now(UTC).isoformat(),
            "price": 100,
            "open": 99,
            "high": 101,
            "low": 98,
            "volume": 100,
            "currency": "peso_Argentino",
        },
    }


def test_instrument_validation_distinguishes_found_not_found_and_cedear():
    responses = {
        "EDN": httpx.Response(200, json=_validation_quote()),
        "AAPL": httpx.Response(
            200, json=_validation_quote(symbol="AAPL", description="Cedear Apple Inc.")
        ),
        "FOND": httpx.Response(
            200, json=_validation_quote(symbol="FOND", description="Fondo Renta Pesos")
        ),
        "XXXXX": httpx.Response(404, json={"ok": False, "error": "QUOTE_NOT_FOUND"}),
    }
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: responses[request.url.path.split("/")[-2]])
    ) as http:
        client = ArgentinaMarketTrackerClient(http, "https://test")
        local = client.validate_instrument("EDN")
        cedear = client.validate_instrument("AAPL")
        other = client.validate_instrument("FOND")
        missing = client.validate_instrument("XXXXX")
        assert local.status == "VALIDATED"
        assert local.classification == "DOMESTIC_EQUITY_CANDIDATE"
        assert local.classification_method == "provider_description_policy"
        assert cedear.status == "UNSUPPORTED"
        assert cedear.classification == "CEDEAR"
        assert other.status == "UNSUPPORTED"
        assert other.classification == "EXCLUDED_INSTRUMENT"
        assert missing.status == "NOT_FOUND"
        assert missing.classification is None


@pytest.mark.parametrize(
    "symbol,description",
    [
        ("TECO2", "Telecom Argentina"),
        ("TGNO4", "Transportadora Gas Del Norte"),
        ("TGSU2", "Transportadora Gas Del Sur"),
        ("A3", "Matba Rofex S.A."),
    ],
)
def test_instrument_validation_accepts_domestic_numeric_suffixes(symbol, description):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, json=_validation_quote(symbol=symbol, description=description)
            )
        )
    ) as http:
        result = ArgentinaMarketTrackerClient(http, "https://test").validate_instrument(symbol)

    assert result.status == "VALIDATED"
    assert result.ticker == symbol
    assert result.classification == "DOMESTIC_EQUITY_CANDIDATE"


@pytest.mark.parametrize(
    "change",
    [
        {"symbol": "PAMP"},
        {"market": "NYSE"},
        {"source": "demo"},
        {"stale": True},
        {"data": {"symbol": "PAMP"}},
        {"data": {"market": "NYSE"}},
    ],
)
def test_instrument_validation_rejects_identity_and_quality_mismatch(change):
    payload = _validation_quote()
    if "data" in change:
        payload["data"].update(change["data"])
    else:
        payload.update(change)
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as http:
        with pytest.raises(ExternalServiceError):
            ArgentinaMarketTrackerClient(http, "https://test").validate_instrument("EDN")


@pytest.mark.parametrize("status", [500, 503])
def test_instrument_validation_provider_error_is_not_not_found(status):
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(status))
    ) as http:
        with pytest.raises(ExternalServiceError):
            ArgentinaMarketTrackerClient(http, "https://test").validate_instrument("EDN")
