from loguru import logger
from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError
from openai.types.chat import ChatCompletionMessageParam
from qdrant_client import QdrantClient
from qdrant_client.http.models.models import ScoredPoint
from sentence_transformers import SentenceTransformer
from sqlmodel import Session
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings
from app.db.qdrant import (
    _vector_to_list,
    delete_by_document_id,
    search_vectors,
    upsert_chunks,
)
from app.db.sqlite import engine
from app.models.domain import Document, DocumentStatus
from app.models.schemas import (
    AnswerSource,
    SearchResultItem,
    SearchResultMetadata,
    StructuredData,
)
from app.utils.text_processing import build_chunks


class DocumentNotFoundError(Exception):
    pass


settings = get_settings()
CLIENT = OpenAI(
    base_url=settings.OPENROUTER_API_URL, api_key=settings.OPENROUTER_API_KEY
)

SYSTEM_PROMPT = """You are an accountant assistant.
You are given a question and a list of sources.
You need to answer the question based on the sources.
Answer only with the information from the sources.
Do not invent any information.
If information is not present in the sources, say "No information available".
"""

USER_PROMPT = """Question: {question}

Context from indexed documents:
{context}

Answer:"""


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


def _format_answer_context(sources: list[AnswerSource]) -> str:
    """Build LLM context from search hits (readable fragments, not Python repr)."""
    blocks = [
        f"--- Fragment {index} (document_id: {source.document_id}) ---\n"
        f"{source.source_text}"
        for index, source in enumerate(sources, start=1)
    ]
    return "\n\n".join(blocks)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=15),
    retry=retry_if_exception_type(
        (APIConnectionError, APITimeoutError, RateLimitError)
    ),
)
def answer_question(question: str, sources: list[AnswerSource]) -> str | None:
    context = _format_answer_context(sources)
    system_prompt: ChatCompletionMessageParam = {
        "role": "system",
        "content": SYSTEM_PROMPT,
    }
    user_prompt: ChatCompletionMessageParam = {
        "role": "user",
        "content": USER_PROMPT.format(question=question, context=context),
    }

    response = CLIENT.chat.completions.create(
        model=settings.LLM_MODEL_NAME,
        messages=[system_prompt, user_prompt],
        temperature=0.0,
        timeout=60,
    )
    return response.choices[0].message.content


def index_all_completed_documents(
    embedder: SentenceTransformer,
    qdrant_client: QdrantClient,
    document_ids: list[str],
) -> dict[str, list]:
    indexed: list[dict[str, object]] = []
    failed: list[dict[str, str]] = []

    for document_id in document_ids:
        try:
            chunks_indexed = index_document(
                document_id=document_id,
                embedder=embedder,
                qdrant_client=qdrant_client,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Indexing failed for document {}", document_id)
            failed.append({"document_id": document_id})
        else:
            indexed.append(
                {"document_id": document_id, "chunks_indexed": chunks_indexed}
            )
    return {
        "indexed": indexed,
        "failed": failed,
    }
