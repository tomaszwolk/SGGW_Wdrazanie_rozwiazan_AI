from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sentence_transformers import SentenceTransformer

from app.api.documents import router as documents_router
from app.api.rag import router as rag_router
from app.core.config import get_settings
from app.db.qdrant import ensure_collection, get_qdrant_client, health_check_qdrant
from app.db.sqlite import check_sqlite, init_db
from app.models.schemas import HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # Create directories if they don't exist
    Path(settings.SQLITE_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

    init_db()
    app.state.embedder = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
    app.state.qdrant_client = get_qdrant_client()
    ensure_collection(app.state.qdrant_client)
    yield


app = FastAPI(lifespan=lifespan)

app.include_router(documents_router)
app.include_router(rag_router)


@app.get("/health", response_model=HealthResponse)  # TODO przenieść do api/health.py
def health_check():
    sqlite_connection = "error" if not check_sqlite() else "ok"
    qdrant_connection = (
        "error" if not health_check_qdrant(app.state.qdrant_client) else "ok"
    )
    status = (
        "error"
        if any([sqlite_connection == "error", qdrant_connection == "error"])
        else "ok"
    )
    code = 200 if status == "ok" else 500
    content = HealthResponse(
        status=status,
        sqlite_connection=sqlite_connection,
        qdrant_connection=qdrant_connection,
    ).model_dump_json()

    return JSONResponse(
        content=content, status_code=code, media_type="application/json"
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
