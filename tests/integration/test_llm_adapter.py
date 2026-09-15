import httpx
import pytest

from merval_agent.adapters.llm.compatible import CompatibleLLMProvider
from merval_agent.domain.errors import ExternalServiceError
from merval_agent.domain.models import AgentState


def test_compatible_provider_transport():
    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"action":"CLARIFY","reason":"Ticker?","confidence":0.5}'
                        }
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        provider = CompatibleLLMProvider(http, "https://llm.test/v1", "test-model", "test-key")
        assert provider.decide(AgentState(user_request="Galicia"), []).action == "CLARIFY"


def test_invalid_llm_json():
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"choices": []}))
    ) as http:
        provider = CompatibleLLMProvider(http, "https://llm.test/v1", "test-model", "test-key")
        with pytest.raises(ExternalServiceError):
            provider.decide(AgentState(user_request="GGAL"), [])
