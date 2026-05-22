from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger

from app.core.config import get_settings
from app.models.schemas import (
    AnswerRequest,
    AnswerResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)
from app.services.rag_service import (
    answer_question,
    enrich_search_results_with_sqlite,
    hybrid_search,
)

settings = get_settings()


def _resolve_top_k(top_k: int | None) -> int:
    """Swagger UI often sends 0 for empty number fields — treat as unset."""
    if top_k is None or top_k < 1:
        return settings.RAG_DEFAULT_TOP_K
    return top_k


router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/search", response_model=SearchResponse)
def search_documents_rag(request: Request, body: SearchRequest) -> JSONResponse:
    top_k = _resolve_top_k(body.top_k)
    try:
        results = hybrid_search(
            query=body.query,
            embedder=request.app.state.embedder,
            qdrant_client=request.app.state.qdrant_client,
            top_k=top_k,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Search failed for query {}", body.query)
        raise HTTPException(status_code=500, detail="Search failed") from None
    results = enrich_search_results_with_sqlite(results)
    return JSONResponse(
        status_code=200,
        content=SearchResponse(query=body.query, results=results).model_dump(
            mode="json"
        ),
    )


@router.post("/answer", response_model=AnswerResponse)
def answer_rag(request: Request, body: AnswerRequest) -> JSONResponse:
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Question is empty") from None

    top_k = _resolve_top_k(body.top_k)
    try:
        results: list[SearchResultItem] = hybrid_search(
            query=question,
            embedder=request.app.state.embedder,
            qdrant_client=request.app.state.qdrant_client,
            top_k=top_k,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Answer failed for question {}", question)
        raise HTTPException(status_code=500, detail="Answer failed") from None

    if not results:
        return JSONResponse(
            status_code=200,
            content=AnswerResponse(
                question=question, answer="No information available", sources=[]
            ).model_dump(mode="json"),
        )

    sources = enrich_search_results_with_sqlite(results)

    try:
        answer = answer_question(question=question, sources=sources)
    except Exception:  # noqa: BLE001
        logger.exception("Answer failed for question {}", question)
        raise HTTPException(status_code=500, detail="Answer failed") from None
    if answer is None:
        raise HTTPException(status_code=500, detail="Answer failed")
    return JSONResponse(
        status_code=200,
        content=AnswerResponse(
            question=question, answer=answer, sources=sources
        ).model_dump(mode="json"),
    )
