from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger

from app.models.schemas import (
    AnswerRequest,
    AnswerResponse,
    AnswerSource,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)
from app.services.rag_service import answer_question, search_documents

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/search", response_model=SearchResponse)
def search_documents_rag(request: Request, body: SearchRequest) -> JSONResponse:
    try:
        results = search_documents(
            query=body.query,
            embedder=request.app.state.embedder,
            qdrant_client=request.app.state.qdrant_client,
            top_k=body.top_k,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Search failed for query {}", body.query)
        raise HTTPException(status_code=500, detail="Search failed") from None
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

    try:
        results: list[SearchResultItem] = search_documents(
            query=question,
            embedder=request.app.state.embedder,
            qdrant_client=request.app.state.qdrant_client,
            top_k=body.top_k,
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

    sources: list[AnswerSource] = [
        AnswerSource(document_id=result.document_id, source_text=result.source_text)
        for result in results
    ]

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
