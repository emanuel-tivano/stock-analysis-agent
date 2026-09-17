from fastapi.testclient import TestClient

from merval_agent.adapters.llm.fake import FakeLLMProvider
from merval_agent.api.app import create_app
from merval_agent.domain.errors import ExternalServiceError


def test_root_and_static_assets_are_served(make_agent):
    agent, _ = make_agent()
    with TestClient(create_app(agent=agent)) as client:
        page = client.get("/")
        css = client.get("/assets/styles.css")
        script = client.get("/assets/app.js")

    assert page.status_code == css.status_code == script.status_code == 200
    assert "Stock Analysis Agent" in page.text
    assert 'aria-live="polite"' in page.text
    assert 'id="conversation"' in page.text
    assert 'class="conversation is-empty"' in page.text
    assert 'data-state="empty"' in page.text
    assert "text/css" in css.headers["content-type"]
    assert "javascript" in script.headers["content-type"]
    assert page.headers["content-security-policy"].startswith("default-src 'self'")
    assert 'addDetailRow(list, "Tendencia"' in script.text
    assert 'addDetailRow(list, "Estado del momentum"' in script.text
    assert 'addDetailRow(list, "ID de ejecución"' in script.text
    assert 'addDetailRow(list, "Trend"' not in script.text
    assert 'addDetailRow(list, "Momentum state"' not in script.text
    assert 'addDetailRow(list, "Trace ID"' not in script.text
    assert 'conversation.classList.toggle("is-empty", empty)' in script.text
    assert 'conversation.dataset.state = empty ? "empty" : "active"' in script.text


def test_chat_returns_human_projection_and_preserves_session(make_agent):
    agent, _ = make_agent()
    with TestClient(create_app(agent=agent)) as client:
        response = client.post(
            "/chat",
            json={"message": "Analizá técnicamente GGAL", "session_id": "web-session"},
        )
        legacy = client.post(
            "/agent/run",
            json={"message": "Analizá técnicamente GGAL", "session_id": "legacy-session"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ANSWER"
    assert body["session_id"] == "web-session"
    assert body["heading"] == "GGAL · Grupo Financiero Galicia"
    assert body["conclusion"]["label"] in ("Alcista", "Bajista", "Mixto", "Neutral")
    assert "indicators" in body and "technical_details" in body
    assert legacy.status_code == 200
    assert legacy.json()["session_id"] == "legacy-session"
    assert "generation" in legacy.json()


def test_chat_rejects_empty_input_with_human_message(make_agent):
    agent, _ = make_agent()
    with TestClient(create_app(agent=agent)) as client:
        response = client.post("/chat", json={"message": "  "})

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "EMPTY_MESSAGE",
        "message": "Escribí una consulta antes de enviarla.",
    }


def test_chat_requests_asset_clarification(make_agent):
    agent, _ = make_agent()
    with TestClient(create_app(agent=agent)) as client:
        body = client.post("/chat", json={"message": "Analizá técnicamente XXXX"}).json()

    assert body["status"] == "CLARIFY"
    assert "ticker" in body["user_message"].lower()


def test_chat_uses_exact_ambiguous_asset_wording(make_agent):
    agent, _ = make_agent()
    with TestClient(create_app(agent=agent)) as client:
        body = client.post("/chat", json={"message": "Analizá Grupo Financiero Galicia"}).json()
        resolved = client.post(
            "/chat", json={"message": "GGAL", "session_id": body["session_id"]}
        ).json()

    expected = (
        "El activo es ambiguo. Indicá el ticker exacto o especificá el instrumento "
        "y mercado que querés analizar."
    )
    assert body["status"] == "CLARIFY"
    assert body["result_type"] == "ambiguous_asset"
    assert body["user_message"] == expected
    assert body["executive_summary"] == expected
    assert resolved["status"] == "ANSWER"
    assert resolved["result_type"] == "successful_analysis"
    assert resolved["ticker"] == "GGAL"
    assert resolved["session_id"] == body["session_id"]


def test_unknown_asset_is_structured_and_has_no_technical_panels(make_agent):
    from unittest.mock import Mock

    agent, _ = make_agent()
    history = Mock(side_effect=AssertionError("market history must not be called"))
    agent.tools.tools["get_market_history"].handler = history
    with TestClient(create_app(agent=agent)) as client:
        chat = client.post("/chat", json={"message": "Analizá técnicamente PPSA"})
        technical = client.post("/agent/run", json={"message": "Analizá técnicamente PPSA"})

    assert chat.status_code == technical.status_code == 200
    chat_body = chat.json()
    assert chat_body["result_type"] == "asset_not_found"
    assert chat_body["heading"] == "Activo no identificado"
    assert "PPSA" in chat_body["user_message"]
    assert "insuficiente" not in chat_body["user_message"].lower()
    assert chat_body["indicators"] == []
    assert chat_body["sources"] == []
    assert chat_body["technical_details"] is None
    technical_body = technical.json()
    assert technical_body["status"] == "CLARIFY"
    assert technical_body["technical"]["status"] == "ASSET_NOT_FOUND"
    assert technical_body["technical"]["assessment"] is None
    assert technical_body["technical"]["metrics"] is None
    assert history.call_count == 0


def test_chat_translates_market_provider_failure(make_agent):
    agent, _ = make_agent(market_status=503)
    with TestClient(create_app(agent=agent)) as client:
        body = client.post("/chat", json={"message": "Técnico GGAL"}).json()

    assert body["status"] == "ERROR"
    assert "datos de mercado" in body["user_message"]
    assert "stack" not in body["user_message"].lower()


def test_chat_translates_llm_timeout(make_agent):
    def timeout(_state):
        raise ExternalServiceError("private timeout")

    agent, _ = make_agent(provider=FakeLLMProvider(timeout))
    with TestClient(create_app(agent=agent)) as client:
        body = client.post("/chat", json={"message": "Técnico GGAL"}).json()

    assert body["status"] == "ERROR"
    assert "no respondió a tiempo" in body["user_message"]
    assert "private" not in body["user_message"]
