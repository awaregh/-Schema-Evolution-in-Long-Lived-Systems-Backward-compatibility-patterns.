import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    DATABASE_URL: str = (
        "postgresql://admin:admin123@localhost:5432/schema_evolution"
    )
    REDIS_URL: str = "redis://localhost:6379/0"
    SERVICE_VERSION: str = "v1"

    # Controls which field names the event consumer reads (v1 or v2)
    CONSUMER_VERSION: str = "v1"

    # Number of events to process per batch
    EVENT_BATCH_SIZE: int = 100

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
