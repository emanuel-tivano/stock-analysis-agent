from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    market_tracker_base_url: str = "https://argentina-market-tracker.vercel.app"
    market_quote_enrichment: bool = True
    market_quote_policy: Literal["include_provisional_ohlc", "history_only"] = (
        "include_provisional_ohlc"
    )
    llm_fallback_enabled: bool = False
    llm_fallback_model: str = ""
    llm_allowed_fallback_models: list[str] = Field(default_factory=list)
    llm_deterministic_fallback: bool = True
    llm_max_retry_wait_seconds: float = Field(default=30, ge=0, le=60)
    bolsar_base_url: str = "https://bolsar.info"
    llm_provider: Literal["fake", "compatible", "gemini"] = "fake"
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_timeout_seconds: float = Field(default=20, gt=0)
    llm_max_retries: int = Field(default=1, ge=0, le=2)
    llm_response_format: Literal["json_object", "json_schema", "none"] = "json_object"
    agent_prompt_version: str = "technical-v3"
    llm_input_price_per_1m: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    llm_output_price_per_1m: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_agent_steps: int = Field(default=12, ge=1, le=100)
    http_timeout_seconds: float = Field(default=20, gt=0)
    database_path: str = "data/sessions.sqlite3"
    stale_after_days: int = Field(default=7, ge=0)

    @model_validator(mode="after")
    def allowed_fallback(self):
        if self.llm_fallback_enabled and (
            not self.llm_fallback_model
            or self.llm_fallback_model == self.llm_model
            or self.llm_fallback_model not in self.llm_allowed_fallback_models
        ):
            raise ValueError("Fallback requires a distinct explicitly allowlisted model")
        return self
