from collections import defaultdict
from uuid import uuid5

import httpx
from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.http.models.models import ScoredPoint
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.config import get_settings
from app.utils.text_processing import ChunkSpec

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


def point_id(document_id: str, section_type: str, index: int = 0) -> str:
    name = f"{document_id}:{section_type}:{index}"
    return str(uuid5(settings.APP_NAMESPACE, name))


def delete_by_document_id(client: QdrantClient, document_id: str) -> None:
    client.delete(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        points_selector=Filter(
            must=[
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=document_id),
                )
            ]
        ),
    )


def _vector_to_list(vector) -> list[float]:
    if hasattr(vector, "tolist"):
        return vector.tolist()
    return list(vector)


def upsert_chunks(
    client: QdrantClient,
    document_id: str,
    chunks: list[ChunkSpec],
    vectors,
) -> None:
    counters: defaultdict[str, int] = defaultdict(int)
    points: list[PointStruct] = []

    for chunk, vector in zip(chunks, vectors, strict=True):
        idx = counters[chunk.section_type]
        counters[chunk.section_type] += 1
        points.append(
            PointStruct(
                id=point_id(document_id, chunk.section_type, idx),
                vector=_vector_to_list(vector),
                payload=chunk.payload,
            )
        )

    client.upsert(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        points=points,
    )


def search_vectors(
    client: QdrantClient, query_vector: list[float], top_k: int
) -> list[ScoredPoint]:
    response = client.query_points(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        query=query_vector,
        limit=top_k,
    )
    return list(response.points)
