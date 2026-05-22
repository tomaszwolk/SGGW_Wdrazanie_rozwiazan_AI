from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from sentence_transformers import SentenceTransformer

from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.rag import router as rag_router
from app.core.config import get_settings
from app.db.qdrant import ensure_collection, get_qdrant_client
from app.db.sqlite import init_db


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
app.include_router(health_router)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
