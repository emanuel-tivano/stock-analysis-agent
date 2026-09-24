from collections.abc import Callable
from datetime import datetime

import httpx

from merval_agent.adapters.bolsar import BolsarClient
from merval_agent.adapters.llm.compatible import CompatibleLLMProvider
from merval_agent.adapters.llm.fake import FakeLLMProvider
from merval_agent.adapters.llm.fallback import ModelFallbackProvider
from merval_agent.adapters.llm.gemini import GeminiLLMProvider
from merval_agent.adapters.market_tracker import ArgentinaMarketTrackerClient
from merval_agent.agents.equity_agent import EquityAgent
from merval_agent.config import Settings
from merval_agent.memory.sqlite import SQLiteRepository
from merval_agent.retrieval.local import LocalMethodologyRetriever
from merval_agent.tools.registry import build_registry


def build_provider(settings: Settings, http: httpx.Client):
    if settings.llm_provider == "fake":
        return FakeLLMProvider()
    provider_type = (
        GeminiLLMProvider if settings.llm_provider == "gemini" else CompatibleLLMProvider
    )
    primary = provider_type(
        http,
        settings.llm_base_url,
        settings.llm_model,
        settings.llm_api_key.get_secret_value(),
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        prompt_version=settings.agent_prompt_version,
        response_format=settings.llm_response_format,
        max_retry_wait_seconds=settings.llm_max_retry_wait_seconds,
    )
    if not settings.llm_fallback_enabled:
        return primary
    backup = provider_type(
        http,
        settings.llm_base_url,
        settings.llm_fallback_model,
        settings.llm_api_key.get_secret_value(),
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        prompt_version=settings.agent_prompt_version,
        response_format=settings.llm_response_format,
        max_retry_wait_seconds=settings.llm_max_retry_wait_seconds,
    )
    return ModelFallbackProvider(primary, backup)


def build_agent(
    settings: Settings,
    http: httpx.Client,
    *,
    clock: Callable[[], datetime] | None = None,
) -> EquityAgent:
    provider = build_provider(settings, http)
    tools = build_registry(
        ArgentinaMarketTrackerClient(
            http,
            settings.market_tracker_base_url,
            enrich_quote=settings.market_quote_enrichment,
            stale_after_days=settings.stale_after_days,
            quote_policy=settings.market_quote_policy,
        ),
        BolsarClient(http, settings.bolsar_base_url),
        LocalMethodologyRetriever(),
    )
    return EquityAgent(
        provider,
        tools,
        SQLiteRepository(settings.database_path),
        settings.max_agent_steps,
        settings.stale_after_days,
        deterministic_fallback=settings.llm_deterministic_fallback,
        clock=clock,
    )
