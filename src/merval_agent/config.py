from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    market_tracker_base_url: str = "https://argentina-market-tracker.vercel.app"
    bolsar_base_url: str = "https://bolsar.info"
    llm_provider: Literal["fake", "compatible"] = "fake"
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: SecretStr = SecretStr("")
    max_agent_steps: int = Field(default=12, ge=1, le=100)
    http_timeout_seconds: float = Field(default=20, gt=0)
    database_path: str = "data/sessions.sqlite3"
    stale_after_days: int = Field(default=7, ge=0)
