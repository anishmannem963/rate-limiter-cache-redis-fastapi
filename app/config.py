from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Scalable API Rate Limiting & Caching System"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Redis
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""

    # PostgreSQL
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "ratelimiter"
    POSTGRES_USER: str = "admin"
    POSTGRES_PASSWORD: str = "secret"

    # Rate Limiting defaults
    DEFAULT_RATE_LIMIT: int = 100       # requests per window
    DEFAULT_WINDOW_SECONDS: int = 60    # window size in seconds
    BURST_MULTIPLIER: float = 1.5       # allow short bursts above limit

    # Cache
    DEFAULT_CACHE_TTL: int = 30         # seconds
    CACHE_MAX_SIZE_MB: int = 256

    # Observability
    LOG_LEVEL: str = "INFO"
    METRICS_WINDOW: int = 60            # seconds to aggregate metrics over

    @property
    def redis_url(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def postgres_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
