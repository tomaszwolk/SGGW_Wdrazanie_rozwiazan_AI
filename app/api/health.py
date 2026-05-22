from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.db.qdrant import health_check_qdrant
from app.db.sqlite import check_sqlite
from app.models.schemas import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse)
def health_check(request: Request):
    sqlite_connection = "error" if not check_sqlite() else "ok"
    qdrant_connection = (
        "error" if not health_check_qdrant(request.app.state.qdrant_client) else "ok"
    )
    status = (
        "error"
        if any([sqlite_connection == "error", qdrant_connection == "error"])
        else "ok"
    )
    code = 200 if status == "ok" else 500
    body = HealthResponse(
        status=status,
        sqlite_connection=sqlite_connection,
        qdrant_connection=qdrant_connection,
    )
    return JSONResponse(content=body.model_dump(), status_code=code)
