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


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def find_completed_documents_by_structured_data_substring(
    term: str,
    *,
    limit: int = 3,
    exclude_document_ids: set[str] | None = None,
) -> list[Document]:
    if not term.strip():
        return []
    exclude = exclude_document_ids or set()
    pattern = f"%{_escape_like(term)}%"
    with Session(engine) as session:
        rows = session.exec(
            select(Document)
            .where(Document.status == DocumentStatus.COMPLETED)
            .where(Document.structured_data.isnot(None))  # type: ignore[union-attr]
            .where(Document.structured_data.like(pattern, escape="\\"))  # type: ignore[union-attr]
            .limit(limit + len(exclude))
        ).all()
    documents: list[Document] = []
    for document in rows:
        if document.id in exclude:
            continue
        documents.append(document)
        if len(documents) >= limit:
            break
    return documents


def find_completed_documents_for_invoice_candidates(
    candidates: list[str],
    *,
    limit: int = 3,
    exclude_document_ids: set[str] | None = None,
) -> list[Document]:
    exclude = set(exclude_document_ids or ())
    found: list[Document] = []
    for term in candidates:
        if len(found) >= limit:
            break
        batch = find_completed_documents_by_structured_data_substring(
            term,
            limit=limit - len(found),
            exclude_document_ids=exclude,
        )
        for document in batch:
            exclude.add(document.id)
            found.append(document)
            if len(found) >= limit:
                break
    return found


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
