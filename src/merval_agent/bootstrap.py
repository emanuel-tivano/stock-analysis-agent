import httpx

from merval_agent.adapters.bolsar import BolsarClient
from merval_agent.adapters.llm.compatible import CompatibleLLMProvider
from merval_agent.adapters.llm.fake import FakeLLMProvider
from merval_agent.adapters.market_tracker import ArgentinaMarketTrackerClient
from merval_agent.agents.equity_agent import EquityAgent
from merval_agent.config import Settings
from merval_agent.memory.sqlite import SQLiteRepository
from merval_agent.retrieval.local import LocalMethodologyRetriever
from merval_agent.tools.registry import build_registry


def build_agent(settings: Settings, http: httpx.Client) -> EquityAgent:
    provider = (
        FakeLLMProvider()
        if settings.llm_provider == "fake"
        else CompatibleLLMProvider(
            http, settings.llm_base_url, settings.llm_model, settings.llm_api_key.get_secret_value()
        )
    )
    tools = build_registry(
        ArgentinaMarketTrackerClient(http, settings.market_tracker_base_url),
        BolsarClient(http, settings.bolsar_base_url),
        LocalMethodologyRetriever(),
    )
    return EquityAgent(
        provider,
        tools,
        SQLiteRepository(settings.database_path),
        settings.max_agent_steps,
        settings.stale_after_days,
    )
