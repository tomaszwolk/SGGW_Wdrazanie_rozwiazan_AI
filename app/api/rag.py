from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger

from app.models.schemas import SearchRequest, SearchResponse
from app.services.rag_service import search_documents

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
