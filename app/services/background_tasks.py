from datetime import UTC, datetime
from pathlib import Path

from loguru import logger
from sqlmodel import Session

from app.db.sqlite import engine
from app.models.domain import Document, DocumentStatus
from app.services.vlm_service import extract_structured_data


def process_document_vlm(
    document_id: str,
    upload_path: Path,
    file_name: str,
    suffix: str,
):
    logger.info("VLM started processing document {}", document_id)

    with Session(engine) as session:
        document = session.get(Document, document_id)
        if not document:
            logger.error("Document not found {}", document_id)
            return
        document.status = DocumentStatus.PROCESSING
        document.updated_at = datetime.now(UTC)
        session.add(document)
        session.commit()

    try:
        vlm_extraction_result = extract_structured_data(upload_path, suffix)
    except Exception as e:
        logger.exception("VLM failed to process document {}", document_id)
        with Session(engine) as session:
            document = session.get(Document, document_id)
            if document:
                document.status = DocumentStatus.FAILED
                document.error_message = str(e)[:500]
                document.updated_at = datetime.now(UTC)
                session.add(document)
                session.commit()
        return

    with Session(engine) as session:
        document = session.get(Document, document_id)
        if not document:
            return
        document.status = DocumentStatus.COMPLETED
        document.raw_text = vlm_extraction_result.raw_text
        document.structured_data = (
            vlm_extraction_result.structured_data.model_dump_json()
        )
        document.error_message = None
        document.updated_at = datetime.now(UTC)
        session.add(document)
        session.commit()

    upload_path.unlink(missing_ok=True)
    logger.info("VLM completed processing document {}", document_id)
