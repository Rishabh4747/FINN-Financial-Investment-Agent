"""
FINN backend configuration — reads from .env file and environment variables.
All settings have safe defaults so the server starts without a .env.
"""
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import model_validator
from functools import lru_cache
import os

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = (BASE_DIR / "finn.db").as_posix()


class Settings(BaseSettings):
    # Server
    host: str = "0.0.0.0"
    port: int = int(os.environ.get("PORT", 8000))
    reload: bool = False

    # Persistent Storage & Database
    # DATA_DIR: directory on persistent disk (e.g. /var/data on Render)
    data_dir: str = ""
    documents_dir: str = ""
    database_url: str = ""

    # CORS settings (comma-separated origins e.g. https://finn.vercel.app)
    cors_origins: str = ""

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

    @model_validator(mode="after")
    def compute_defaults(self) -> "Settings":
        # Resolve database_url from data_dir if not explicitly provided
        if not self.database_url:
            if self.data_dir:
                d = Path(self.data_dir).resolve()
                d.mkdir(parents=True, exist_ok=True)
                self.database_url = f"sqlite:///{(d / 'finn.db').as_posix()}"
            else:
                self.database_url = f"sqlite:///{DEFAULT_DB_PATH}"

        # Resolve documents_dir from data_dir if not explicitly provided
        if not self.documents_dir:
            if self.data_dir:
                self.documents_dir = (Path(self.data_dir).resolve() / "documents").as_posix()
            else:
                self.documents_dir = (BASE_DIR / "documents").as_posix()

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def get_documents_dir() -> Path:
    settings = get_settings()
    p = Path(settings.documents_dir).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p

