from fastapi.testclient import TestClient

from merval_agent.adapters.llm.fake import FakeLLMProvider
from merval_agent.api.app import create_app
from merval_agent.domain.errors import ExternalServiceError
from merval_agent.domain.models import AgentDecision


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
    assert page.headers["cache-control"] == "no-store"
    assert css.headers["cache-control"] == "no-store"
    assert script.headers["cache-control"] == "no-store"
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


def test_cedear_is_presented_as_identified_but_unsupported(make_agent):
    agent, _ = make_agent(validation_quotes={"AAPL": "Cedear Apple Inc."})
    with TestClient(create_app(agent=agent)) as client:
        chat = client.post("/chat", json={"message": "Analizá técnicamente AAPL"})
        technical = client.post("/agent/run", json={"message": "Analizá técnicamente AAPL"})

    assert chat.status_code == technical.status_code == 200
    chat_body = chat.json()
    assert chat_body["status"] == "ABSTAIN"
    assert chat_body["result_type"] == "unsupported_asset"
    assert chat_body["heading"] == "Instrumento fuera de alcance"
    assert chat_body["ticker"] == "AAPL"
    assert chat_body["indicators"] == []
    technical_body = technical.json()
    assert technical_body["ticker"] == "AAPL"
    assert technical_body["technical"]["status"] == "UNSUPPORTED_ASSET"
    assert technical_body["technical"]["assessment"] is None


def test_telecom_name_and_teco2_ticker_converge_across_public_endpoints(make_agent):
    fallback = FakeLLMProvider()

    def script(state):
        if not state.observations and "Telecom" in state.user_request:
            return AgentDecision(
                action="CALL_TOOL",
                tool_name="resolve_asset",
                tool_args={
                    "query": state.user_request,
                    "symbol": "TECO2",
                    "market": "bCBA",
                    "company_name": "Telecom Argentina",
                },
                intent={"analysis_type": "technical"},
                reason="Semantic Telecom proposal",
                confidence=1,
            )
        return fallback.decide(state, [])

    chat_agent, _ = make_agent(
        provider=FakeLLMProvider(script), validation_quotes={"TECO2": "Telecom Argentina"}
    )
    technical_agent, _ = make_agent(validation_quotes={"TECO2": "Telecom Argentina"})
    with TestClient(create_app(agent=chat_agent)) as client:
        chat = client.post("/chat", json={"message": "Analizá técnicamente Telecom"})
    with TestClient(create_app(agent=technical_agent)) as client:
        technical = client.post("/agent/run", json={"message": "Analizá técnicamente TECO2"})

    assert chat.status_code == technical.status_code == 200
    assert chat.json()["status"] == "ANSWER"
    assert chat.json()["result_type"] == "successful_analysis"
    assert chat.json()["ticker"] == "TECO2"
    assert technical.json()["status"] == "ANSWER"
    assert technical.json()["ticker"] == "TECO2"


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
