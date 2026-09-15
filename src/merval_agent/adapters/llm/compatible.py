"""Opt-in chat-completions HTTP adapter. No vendor SDK enters the core."""

import json
from importlib.resources import files

import httpx

from merval_agent.domain.errors import ExternalServiceError
from merval_agent.domain.models import AgentDecision, AgentState


class CompatibleLLMProvider:
    def __init__(self, http: httpx.Client, base_url: str, model: str, api_key: str):
        if not base_url or not model or not api_key:
            raise ValueError("Configure LLM_BASE_URL, LLM_MODEL and LLM_API_KEY")
        self.http, self.base_url, self.model, self.api_key = (
            http,
            base_url.rstrip("/"),
            model,
            api_key,
        )
        folder = files("merval_agent").joinpath("skills/merval_equity_analysis")
        self.instructions = "\n".join(
            folder.joinpath(p).read_text(encoding="utf-8")
            for p in ("SKILL.md", "references/contracts.md", "references/tools.md")
        )

    def decide(self, state: AgentState, tools: list[dict]) -> AgentDecision:
        system = (
            self.instructions
            + "\nReturn one JSON AgentDecision. Schema:\n"
            + json.dumps(AgentDecision.model_json_schema())
        )
        try:
            response = self.http.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {"state": state.model_dump(mode="json"), "tools": tools},
                                ensure_ascii=False,
                            ),
                        },
                    ],
                },
            )
            response.raise_for_status()
            return AgentDecision.model_validate_json(
                response.json()["choices"][0]["message"]["content"]
            )
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise ExternalServiceError("LLM unavailable or invalid decision") from exc
