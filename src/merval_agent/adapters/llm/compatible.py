"""OpenAI-compatible transport; shared validation remains vendor independent."""

from merval_agent.domain.models import AgentDecision

from .http_provider import HTTPDecisionProvider


class CompatibleLLMProvider(HTTPDecisionProvider):
    def request(self, messages):
        body = {"model": self.model, "messages": messages, "temperature": 0}
        if self.response_format == "json_object":
            body["response_format"] = {"type": "json_object"}
        elif self.response_format == "json_schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "AgentDecision",
                    "schema": AgentDecision.model_json_schema(),
                },
            }
        return self.http.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=body,
            timeout=self.timeout,
        )

    def normalize(self, payload, metadata):
        raw_usage = payload.get("usage")
        if isinstance(raw_usage, dict):
            metadata["usage"] = {
                k: v
                for k, v in raw_usage.items()
                if k in ("prompt_tokens", "completion_tokens", "total_tokens")
                and type(v) is int
                and v >= 0
            }
        return payload["choices"][0]["message"]["content"]
