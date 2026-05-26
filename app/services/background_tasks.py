from datetime import UTC, datetime
from pathlib import Path

from loguru import logger
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer
from sqlmodel import Session

from app.db.sqlite import engine
from app.models.domain import Document, DocumentStatus
from app.services.rag_service import index_all_completed_documents
from app.services.vlm_service import extract_structured_data


def process_document_vlm(
    document_id: str,
    upload_path: Path,
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
    except Exception as e:  # noqa: BLE001
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


def process_index_all_documents(
    embedder: SentenceTransformer,
    qdrant_client: QdrantClient,
    document_ids: list[str],
) -> None:
    logger.info("Indexing all completed documents")
    summary = index_all_completed_documents(embedder, qdrant_client, document_ids)
    logger.info(
        "Bulk index finished: {} indexed, {} failed",
        len(summary["indexed"]),
        len(summary["failed"]),
    )
