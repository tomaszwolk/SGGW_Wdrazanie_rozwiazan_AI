import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse
from loguru import logger
from sqlmodel import Session

from app.core.config import get_settings
from app.db.sqlite import get_document, get_session, list_completed_document_ids
from app.models.domain import Document, DocumentStatus
from app.models.schemas import (
    BulkIndexResponse,
    DocumentDetailResponse,
    IndexResponse,
    StructuredData,
    UploadResponse,
)
from app.services.background_tasks import (
    process_document_vlm,
    process_index_all_documents,
)
from app.services.rag_service import (
    DocumentNotCompletedError,
    DocumentNotFoundError,
    index_document,
)
from app.utils.upload_validation import validate_upload_file

router = APIRouter(prefix="/documents", tags=["documents"])

settings = get_settings()


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    session: Annotated[Session, Depends(get_session)],
):
    # validate filename
    try:
        suffix = validate_upload_file(file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    document_id = str(uuid.uuid4())

    # save file to disk
    upload_path = Path(settings.UPLOAD_DIR) / f"{document_id}.{suffix}"
    with upload_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    file_name = file.filename or "uploaded_file"
    # create document record in database
    document = Document(
        id=document_id,
        filename=file_name,
        status=DocumentStatus.QUEUED,
        raw_text=None,
        structured_data=None,
        error_message=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(document)
    session.commit()

    # start background task to process document
    background_tasks.add_task(
        process_document_vlm, document_id, upload_path, suffix
    )

    return JSONResponse(
        status_code=202,
        content=UploadResponse(
            document_id=document_id,
            status=DocumentStatus.QUEUED,
            message=f"Document {document_id} uploaded successfully",
        ).model_dump(),
    )


@router.get("/{document_id}", response_model=DocumentDetailResponse)
async def get_document_detail(
    document_id: UUID, session: Annotated[Session, Depends(get_session)]
) -> JSONResponse:
    document = get_document(document_id, session)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    structured_data = None
    raw_text = None
    if document.status == DocumentStatus.COMPLETED and document.structured_data:
        structured_data = StructuredData.model_validate_json(document.structured_data)
        raw_text = document.raw_text

    return JSONResponse(
        status_code=200,
        content=DocumentDetailResponse(
            document_id=str(document_id),
            status=document.status,
            raw_text=raw_text,
            structured_data=structured_data,
            error_message=document.error_message,
        ).model_dump(),
    )


@router.post("/{document_id}/index", response_model=IndexResponse)
async def index_document_rag(document_id: UUID, request: Request) -> JSONResponse:
    doc_id = str(document_id)
    try:
        chunks_indexed = index_document(
            document_id=doc_id,
            embedder=request.app.state.embedder,
            qdrant_client=request.app.state.qdrant_client,
        )
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found") from None
    except DocumentNotCompletedError:
        raise HTTPException(
            status_code=409,
            detail="Document is not completed and cannot be indexed",
        ) from None
    except Exception:  # noqa: BLE001
        logger.exception("Indexing failed for document {}", doc_id)
        raise HTTPException(
            status_code=500,
            detail="Failed to index document (embedding or Qdrant error)",
        ) from None

    message = (
        "No chunks to index"
        if chunks_indexed == 0
        else "Document was indexed successfully."
    )
    return JSONResponse(
        status_code=200,
        content=IndexResponse(
            document_id=doc_id,
            message=message,
            chunks_indexed=chunks_indexed,
        ).model_dump(),
    )


@router.post("/index-all", response_model=BulkIndexResponse)
async def index_all_documents_rag(
    background_tasks: BackgroundTasks, request: Request
) -> JSONResponse:
    document_ids = list_completed_document_ids()
    if not document_ids:
        return JSONResponse(
            status_code=200,
            content=BulkIndexResponse(
                message="No completed documents to index",
                documents_queued=0,
                document_ids=[],
            ).model_dump(),
        )

    background_tasks.add_task(
        process_index_all_documents,
        request.app.state.embedder,
        request.app.state.qdrant_client,
        document_ids,
    )
    return JSONResponse(
        status_code=202,
        content=BulkIndexResponse(
            message="Indexing all completed documents",
            documents_queued=len(document_ids),
            document_ids=document_ids,
        ).model_dump(),
    )
