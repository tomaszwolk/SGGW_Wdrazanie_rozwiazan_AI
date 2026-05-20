import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlmodel import Session

from app.core.config import get_settings
from app.db.sqlite import get_document, get_session
from app.models.domain import Document, DocumentStatus
from app.models.schemas import DocumentDetailResponse, StructuredData, UploadResponse
from app.services.background_tasks import process_document_vlm
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
        process_document_vlm, document, document_id, upload_path, file_name, suffix
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
    if document.status == DocumentStatus.COMPLETED:
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
