from pydantic import BaseModel

from app.models.domain import DocumentStatus


class HealthResponse(BaseModel):
    status: str
    sqlite_connection: str
    qdrant_connection: str


class InvoiceItem(BaseModel):
    item_name: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    total_line_net: float | None = None
    total_line_gross: float | None = None


class StructuredData(BaseModel):
    invoice_no: str | None = None
    date: str | None = None
    buyer: str | None = None
    seller: str | None = None
    currency: str | None = None
    total_net: float | None = None
    total_vat: float | None = None
    total_gross: float | None = None
    items: list[InvoiceItem] | None = None


class VlmExtractionResult(BaseModel):
    raw_text: str
    structured_data: StructuredData


class UploadResponse(BaseModel):
    document_id: str
    status: DocumentStatus = DocumentStatus.QUEUED
    message: str


class DocumentDetailResponse(BaseModel):
    document_id: str
    status: DocumentStatus
    raw_text: str | None = None
    structured_data: StructuredData | None = None
    error_message: str | None = None


class IndexResponse(BaseModel):
    document_id: str
    message: str
    chunks_indexed: int


class SearchRequest(BaseModel):
    query: str
    top_k: int = 3


class SearchResultMetadata(BaseModel):
    filename: str | None = None
    date: str | None = None


class SearchResultItem(BaseModel):
    document_id: str
    score: float
    section_type: str
    source_text: str
    metadata: SearchResultMetadata


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem]
