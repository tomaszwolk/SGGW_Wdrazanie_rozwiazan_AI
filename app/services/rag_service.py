from qdrant_client import QdrantClient
from qdrant_client.http.models.models import ScoredPoint
from sentence_transformers import SentenceTransformer
from sqlmodel import Session

from app.db.qdrant import (
    _vector_to_list,
    delete_by_document_id,
    search_vectors,
    upsert_chunks,
)
from app.db.sqlite import engine
from app.models.domain import Document, DocumentStatus
from app.models.schemas import (
    SearchResultItem,
    SearchResultMetadata,
    StructuredData,
)
from app.utils.text_processing import build_chunks


class DocumentNotFoundError(Exception):
    pass


class DocumentNotCompletedError(Exception):
    pass


def index_document(
    *,
    document_id: str,
    embedder: SentenceTransformer,
    qdrant_client: QdrantClient,
) -> int:
    with Session(engine) as session:
        document = session.get(Document, document_id)
    if document is None:
        raise DocumentNotFoundError(document_id)
    if document.status != DocumentStatus.COMPLETED:
        raise DocumentNotCompletedError(document_id)

    structured = StructuredData.model_validate_json(document.structured_data or "{}")
    chunks = build_chunks(structured, document_id, document.filename)

    delete_by_document_id(qdrant_client, document_id)
    if not chunks:
        return 0

    texts = [chunk.source_text for chunk in chunks]
    vectors = embedder.encode(texts)
    upsert_chunks(qdrant_client, document_id, chunks, vectors)
    return len(chunks)


def _scored_point_to_result(hit: ScoredPoint) -> SearchResultItem:
    payload = hit.payload or {}
    return SearchResultItem(
        document_id=str(payload.get("document_id", "")),
        score=float(hit.score or 0.0),
        section_type=str(payload.get("section_type", "")),
        source_text=str(payload.get("source_text", "")),
        metadata=SearchResultMetadata(
            filename=payload.get("filename"),
            date=payload.get("date"),
        ),
    )


def search_documents(
    query: str,
    embedder: SentenceTransformer,
    qdrant_client: QdrantClient,
    top_k: int = 3,
) -> list[SearchResultItem]:
    query_vector = _vector_to_list(embedder.encode(query))
    hits = search_vectors(qdrant_client, query_vector, top_k)
    return [_scored_point_to_result(hit) for hit in hits]
