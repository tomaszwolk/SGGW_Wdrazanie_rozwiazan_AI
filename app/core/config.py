from pydantic_settings import BaseSettings


class Settings(BaseSettings):
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
