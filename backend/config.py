"""
FINN backend configuration — reads from .env file.
All settings have safe defaults so the server starts without a .env.
"""
from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = (BASE_DIR / "finn.db").as_posix()


class Settings(BaseSettings):
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = True

    # Database — defaults to backend/finn.db absolute path
    database_url: str = f"sqlite:///{DEFAULT_DB_PATH}"

    # API keys
    anthropic_api_key: str = ""

    # yfinance
    yf_history_days: int = 30
    yf_avg_vol_window: int = 20

    # Scheduling
    nse_fetch_interval: int = 300
    price_refresh_interval: int = 86400

    # HTTP
    http_timeout: int = 15

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
