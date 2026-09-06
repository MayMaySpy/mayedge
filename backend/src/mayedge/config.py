from enum import StrEnum

from pydantic_settings import BaseSettings, SettingsConfigDict


class LighterNetwork(StrEnum):
    TESTNET = "testnet"
    MAINNET = "mainnet"


NETWORK_HOSTS = {
    LighterNetwork.TESTNET: "https://testnet.zklighter.elliot.ai",
    LighterNetwork.MAINNET: "https://mainnet.zklighter.elliot.ai",
}

NETWORK_WS = {
    LighterNetwork.TESTNET: "wss://testnet.zklighter.elliot.ai/stream",
    LighterNetwork.MAINNET: "wss://mainnet.zklighter.elliot.ai/stream",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    lighter_network: LighterNetwork = LighterNetwork.TESTNET
    lighter_account_index: int | None = None
    lighter_api_key_index: int = 2
    lighter_api_private_key: str | None = None
    default_market_symbol: str = "LIT"
    db_path: str = "./data/mayedge.db"
    web_root: str = ""
    alerts_config: str = "./config/alerts.yaml"
    liq_subscribe_mode: str = "all"
    bind_host: str = "127.0.0.1"
    bind_port: int = 8000
    max_order_notional: float | None = 50_000.0
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:14200",
        "http://127.0.0.1:14200",
    ]

    @property
    def base_url(self) -> str:
        return NETWORK_HOSTS[self.lighter_network]

    @property
    def ws_url(self) -> str:
        return NETWORK_WS[self.lighter_network]

    @property
    def trading_enabled(self) -> bool:
        return bool(self.lighter_api_private_key and self.lighter_account_index is not None)


settings = Settings()
