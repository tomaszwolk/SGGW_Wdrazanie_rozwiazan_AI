from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

env_file = Path(__file__).parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=env_file, env_file_encoding="utf-8", extra="ignore"
    )
    OPENROUTER_API_KEY: str
    VLM_MODEL_NAME: str
    LLM_MODEL_NAME: str
    QDRANT_HOST: str
    QDRANT_PORT: int
    QDRANT_COLLECTION_NAME: str
    EMBEDDING_MODEL_NAME: str
    SQLITE_PATH: str
    UPLOAD_DIR: str
    CHUNK_MAX_TOKENS: int


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
