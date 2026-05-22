from uuid import UUID

from loguru import logger
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import get_settings
from app.models.domain import Document, DocumentStatus

settings = get_settings()
engine = create_engine(
    f"sqlite:///{settings.SQLITE_PATH}",
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


def check_sqlite() -> bool:
    try:
        with Session(engine) as session:
            session.exec(select(Document).limit(1))
    except SQLAlchemyError:
        logger.exception("Error checking SQLite")
        return False
    else:
        return True


def get_document(document_id: UUID, session: Session) -> Document | None:
    return session.get(Document, str(document_id))


def list_completed_document_ids() -> list[str]:
    with Session(engine) as session:
        rows = session.exec(
            select(Document.id).where(Document.status == DocumentStatus.COMPLETED)
        ).all()
    return list(rows)


def get_completed_documents_by_ids(document_ids: list[str]) -> list[Document]:
    if not document_ids:
        return []
    with Session(engine) as session:
        documents: list[Document] = []
        for document_id in document_ids:
            document = session.get(Document, document_id)
            if (
                document is not None
                and document.status == DocumentStatus.COMPLETED
            ):
                documents.append(document)
        return documents
