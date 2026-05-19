import uuid
from datetime import UTC, datetime
from enum import Enum

from sqlmodel import Field, SQLModel


class DocumentStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Document(SQLModel, table=True):
    __tablename__ = "documents"  # type: ignore[assignment]

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid.uuid4()))
    filename: str
    status: DocumentStatus = Field(default=DocumentStatus.QUEUED)
    raw_text: str | None = None
    structured_data: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
