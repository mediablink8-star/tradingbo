"""Runtime settings from environment. Never commit secrets."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "TradingLab API"
    env: Literal["dev", "paper", "live"] = "paper"

    max_per_trade_usd: float = 12.0
    max_daily_loss_usd: float = 25.0
    max_open_positions: int = 2
    max_exposure_usd: float = 30.0
    arm_ttl_hours: float = 24.0

    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"

    oanda_api_key: str = ""
    oanda_account_id: str = ""
    oanda_base_url: str = "https://api-fxpractice.oanda.com"

    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    solana_private_key: str = ""

    llm_api_key: str = ""
    llm_base_url: str = "https://api.x.ai/v1"
    llm_model: str = "grok-2-latest"


@lru_cache
def get_settings() -> Settings:
    return Settings()
