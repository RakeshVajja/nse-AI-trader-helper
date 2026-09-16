"""Application settings and environment configuration."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration parameters for the backend API."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General Application
    PROJECT_NAME: str = "NSE AI Trading Agent & Simulator"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    WEB_PORT: int = 3000
    API_V1_STR: str = "/api/v1"
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
    ]

    # Database
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "nse_trader"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/nse_trader"
    DATABASE_SYNC_URL: str = "postgresql://postgres:postgres@localhost:5432/nse_trader"

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_URL: str = "redis://localhost:6379/0"

    # AI (Gemini)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # Default Trading & Risk Constraints
    DEFAULT_INITIAL_CAPITAL: float = 100000.0
    DEFAULT_MAX_RISK_PER_TRADE: float = 0.02
    DEFAULT_MAX_POSITION_EXPOSURE: float = 0.25
    DEFAULT_MAX_DAILY_LOSS: float = 0.05
    DEFAULT_SLIPPAGE_PCT: float = 0.0005
    DEFAULT_BROKERAGE_PCT: float = 0.0003

    # Market Data
    DATA_CACHE_TTL_SECONDS: int = 3600
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 30


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
