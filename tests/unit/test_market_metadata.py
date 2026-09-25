from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from merval_agent.adapters.market_tracker import ArgentinaMarketTrackerClient
from merval_agent.agents.report import build_report
from merval_agent.api.app import create_app
from merval_agent.config import Settings
from merval_agent.domain.models import AgentState, AssetResolution, UserIntent
from merval_agent.domain.technical import calculate
from merval_agent.domain.technical_assessment import assess
from merval_agent.presentation.presenter import present_analysis

AT = datetime(2026, 9, 24, 22, tzinfo=UTC)


def history(*, variant="ajustada", volume=100, last_volume=100, quote=True):
    meta = {"source": "live", "stale": False}
    if variant is not None:
        meta["resolvedVariant"] = variant
    payload = {
        "ok": True,
        "symbol": "GGAL",
        "market": "bCBA",
        "range": "6M",
        "fetchedAt": AT.isoformat(),
        "meta": meta,
        "data": [
            {
                "date": (AT.date() - timedelta(days=60 - i)).isoformat(),
                "open": 100 + i,
                "high": 102 + i,
                "low": 99 + i,
                "close": 101 + i,
                "volume": last_volume if i == 59 else volume,
                "currency": "ARS",
            }
            for i in range(60)
        ],
    }
    quote_payload = {
        "ok": True,
        "symbol": "GGAL",
        "market": "bCBA",
        "source": "live",
        "stale": False,
        "data": {
            "timestamp": "2026-09-24T17:00:02.6429154-03:00",
            "price": 160,
            "open": 159,
            "high": 161,
            "low": 158,
            "volume": 1959017,
            "currency": "ARS",
        },
    }
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=quote_payload if request.url.path.endswith("quote") else payload
            )
        )
    ) as http:
        return ArgentinaMarketTrackerClient(
            http, "https://market.test", clock=lambda: AT, enrich_quote=quote
        ).get_history("GGAL", "6M")


def report(h):
    return build_report(
        AgentState(
            user_request="Técnico GGAL",
            status="ANSWER",
            intent=UserIntent(analysis_type="technical"),
            resolved_asset=AssetResolution(ticker="GGAL", confidence=1),
            technical_data=h,
            technical_metrics=calculate(h.bars),
        ),
        "",
        "",
        7,
        reference_time=AT,
    )


@pytest.mark.parametrize("variant", ["ajustada", "sin_ajustar", None])
def test_variant_survives_adapter_report_and_presentation(variant):
    h = history(variant=variant)
    result = report(h)
    chat = present_analysis(result)
    assert h.resolved_variant == result.technical.assessment.basis.resolved_variant == variant
    assert result.technical.evidence[0].metadata["resolved_variant"] == variant
    assert chat.technical_details.resolved_variant == variant
    notes = " ".join(chat.technical_details.warnings)
    if variant == "ajustada":
        assert "Serie histórica ajustada según" in notes
        assert "no se verificaron ajustes corporativos" not in notes
    elif variant:
        assert variant in notes
    else:
        assert "no se verificaron ajustes corporativos" in notes
    assert next(m.label for m in chat.indicators if m.key == "change_percent") == "Variación 6M"


@pytest.mark.parametrize(
    "volume,last_volume,expected",
    [
        (100, 100, "NOT_CONFIRMED"),
        (100, 101, "CONFIRMED"),
        (100, 99, "NOT_CONFIRMED"),
        (0, 1, "NOT_CONFIRMED"),
        (None, 200, "UNAVAILABLE"),
        (100, None, "UNAVAILABLE"),
    ],
)
@pytest.mark.parametrize("quote", [False, True])
def test_volume_availability_and_existing_threshold(volume, last_volume, expected, quote):
    h = history(volume=volume, last_volume=last_volume, quote=quote)
    result = report(h)
    a = result.technical.assessment
    chat = present_analysis(result)
    assert a.volume_confirmation == expected
    assert chat.technical_details.volume_confirmation.code == expected
    if expected != "UNAVAILABLE":
        assert a.volume_as_of == AT.date() - timedelta(days=1)
        notes = " ".join([*chat.warnings, *chat.technical_details.warnings])
        assert "Volumen incompleto" not in notes
        assert "average_volume no se calcula" not in notes
        assert "no hay información suficiente para confirmar" not in notes
    else:
        assert any("Volumen incompleto" in w for w in a.warnings)
    assert result.technical.metrics == calculate(h.bars)


def test_provisional_volume_does_not_confirm_historical_signal():
    h = history(last_volume=100)
    a = assess(h, calculate(h.bars), AT)
    assert h.quote.provisional and a.basis.quote_provisional
    assert a.volume_confirmation == "NOT_CONFIRMED"
    assert a.volume_as_of < h.quote.bar.date


def test_ggal_agent_and_chat_offline_smoke(make_agent):
    h = history(last_volume=200)
    agent, _ = make_agent(clock=lambda: AT)
    agent.tools.tools["get_market_history"].handler = lambda args, state: h.model_dump(mode="json")
    with TestClient(create_app(agent=agent, settings=Settings(_env_file=None))) as client:
        raw = client.post("/agent/run", json={"message": "Analizá técnicamente GGAL"})
        human = client.post("/chat", json={"message": "Analizá técnicamente GGAL"})
    assert raw.status_code == human.status_code == 200
    assert raw.json()["status"] == human.json()["status"] == "ANSWER"
    a = raw.json()["technical"]["assessment"]
    assert a["volume_confirmation"] == "CONFIRMED"
    assert a["basis"]["resolved_variant"] == "ajustada"
    assert human.json()["technical_details"]["volume_confirmation"]["code"] == "CONFIRMED"
    assert human.json()["technical_details"]["resolved_variant"] == "ajustada"
    assert a["volume_as_of"] == "2026-09-23"
    details = human.json()["technical_details"]
    assert details["volume_as_of"] == a["volume_as_of"]
    assert (
        details["volume_confirmation"]["label"]
        == "Confirma el movimiento de la última barra histórica"
    )
    assert details["confirmation"] == {
        "code": "UNCONFIRMED",
        "label": "Sin alineación conjunta de los indicadores",
        "short_label": "Sin alineación conjunta de los indicadores",
    }
    assert any("Datos provisionales" in warning for warning in human.json()["warnings"])
    assert a["basis"]["quote_provisional"] is True
