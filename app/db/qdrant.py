import httpx
from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from app.core.config import get_settings

settings = get_settings()


def get_qdrant_client() -> QdrantClient:
    return QdrantClient(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
    )


def ensure_collection(client: QdrantClient | None = None) -> None:
    if client is None:
        client = get_qdrant_client()
    if client.collection_exists(settings.QDRANT_COLLECTION_NAME):
        return
    client.create_collection(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        vectors_config=VectorParams(size=384, distance=Distance.COSINE),
    )


def health_check_qdrant(client: QdrantClient) -> bool:
    try:
        client.get_collection(settings.QDRANT_COLLECTION_NAME)
    except httpx.HTTPError:
        logger.exception("Error checking Qdrant")
        return False
    else:
        return True
