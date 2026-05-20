# TODO
from pathlib import Path

from fastapi import HTTPException
from sqlmodel import Session

from app.db.sqlite import engine
from app.models.domain import Document, DocumentStatus
from app.services.vlm_service import extract_structured_data


def process_document_vlm(
    document: Document,
    document_id: str,
    upload_path: Path,
    file_name: str,
    suffix: str,
):
    try:
        vlm_extraction_result = extract_structured_data(upload_path, suffix)
    except Exception as e:
        with Session(engine) as session:
            document.status = DocumentStatus.FAILED
            document.error_message = str(e)
            session.commit()
        return

    vlm_extraction_result.structured_data.filename = file_name
    with Session(engine) as session:
        document.status = DocumentStatus.COMPLETED
        document.raw_text = vlm_extraction_result.raw_text
        document.structured_data = (
            vlm_extraction_result.structured_data.model_dump_json()
        )
        session.commit()
