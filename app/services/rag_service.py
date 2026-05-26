import json

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
from app.db.sqlite import (
    engine,
    find_completed_documents_for_invoice_candidates,
    get_completed_documents_by_ids,
)
from app.models.domain import Document, DocumentStatus
from app.models.schemas import (
    SearchResultItem,
    SearchResultMetadata,
    StructuredData,
)
from app.utils.query_parsing import extract_invoice_number_candidates
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


SQL_MATCH_SCORE = 1.0
SQL_APPEND_MAX_DOCUMENTS = 3
# Fallback source_text for sql_match hits when invoice_no is missing (JSON preview).
SQL_MATCH_SOURCE_TEXT_MAX_LEN = 500


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
    top_k: int | None = None,
) -> list[SearchResultItem]:
    if top_k is None:
        top_k = settings.RAG_DEFAULT_TOP_K
    query_vector = _vector_to_list(embedder.encode(query))
    hits = search_vectors(qdrant_client, query_vector, top_k)
    return [_scored_point_to_result(hit) for hit in hits]


def _document_to_sql_search_result(document: Document) -> SearchResultItem:
    structured = StructuredData.model_validate_json(document.structured_data or "{}")
    if structured.invoice_no:
        source_text = f"invoice_no: {structured.invoice_no}"
    else:
        raw = document.structured_data or "{}"
        source_text = raw[:SQL_MATCH_SOURCE_TEXT_MAX_LEN]
    return SearchResultItem(
        document_id=document.id,
        score=SQL_MATCH_SCORE,
        section_type="sql_match",
        source_text=source_text,
        metadata=SearchResultMetadata(
            filename=document.filename,
            date=structured.date,
        ),
    )


def hybrid_search(
    query: str,
    embedder: SentenceTransformer,
    qdrant_client: QdrantClient,
    top_k: int | None = None,
) -> list[SearchResultItem]:
    """Qdrant vector search, then up to 3 SQLite hits not already in vector results."""
    vector_hits = search_documents(query, embedder, qdrant_client, top_k=top_k)
    vector_ids = {hit.document_id for hit in vector_hits}
    candidates = extract_invoice_number_candidates(query)
    if not candidates:
        return vector_hits

    sql_documents = find_completed_documents_for_invoice_candidates(
        candidates,
        limit=SQL_APPEND_MAX_DOCUMENTS,
        exclude_document_ids=vector_ids,
    )
    sql_hits = [_document_to_sql_search_result(document) for document in sql_documents]
    return vector_hits + sql_hits


def _format_structured_data_json(raw: str) -> str:
    if not raw or raw.strip() == "":
        return "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return json.dumps(data, indent=2, ensure_ascii=False)


def _unique_document_ids(results: list[SearchResultItem]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for hit in results:
        if hit.document_id not in seen:
            seen.add(hit.document_id)
            ordered.append(hit.document_id)
    return ordered


def _load_entire_documents_by_id(document_ids: list[str]) -> dict[str, str]:
    documents = get_completed_documents_by_ids(document_ids)
    return {
        document.id: _format_structured_data_json(document.structured_data or "{}")
        for document in documents
    }


def enrich_search_results_with_sqlite(
    results: list[SearchResultItem],
) -> list[SearchResultItem]:
    """Attach formatted structured_data to every hit (API response, proposal A)."""
    entire_by_id = _load_entire_documents_by_id(_unique_document_ids(results))
    enriched: list[SearchResultItem] = []
    for hit in results:
        metadata = hit.metadata.model_copy(
            update={
                "entire_document": entire_by_id.get(hit.document_id),
            }
        )
        enriched.append(hit.model_copy(update={"metadata": metadata}))
    return enriched


def _best_hit_index_per_document(results: list[SearchResultItem]) -> dict[str, int]:
    best: dict[str, int] = {}
    for index, hit in enumerate(results):
        document_id = hit.document_id
        if document_id not in best or hit.score > results[best[document_id]].score:
            best[document_id] = index
    return best


def _format_answer_context(results: list[SearchResultItem]) -> str:
    best_index = _best_hit_index_per_document(results)
    blocks: list[str] = []
    for index, hit in enumerate(results, start=1):
        label = (
            f"--- Source {index} | document_id: {hit.document_id}"
            f" | section: {hit.section_type} | score: {hit.score:.4f} ---"
        )
        parts = [hit.source_text]
        entire = hit.metadata.entire_document
        if entire and best_index.get(hit.document_id) == index - 1:
            parts.append(f"\nFull document (structured_data):\n{entire}")
        blocks.append(f"{label}\n{''.join(parts)}")
    return "\n\n".join(blocks)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=15),
    retry=retry_if_exception_type(
        (APIConnectionError, APITimeoutError, RateLimitError)
    ),
)
def answer_question(question: str, sources: list[SearchResultItem]) -> str | None:
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
