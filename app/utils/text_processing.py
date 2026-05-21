from dataclasses import dataclass

from loguru import logger

from app.core.config import get_settings
from app.models.schemas import InvoiceItem, StructuredData

settings = get_settings()

HEADER_SECTION = ["invoice_no", "date", "buyer", "seller", "currency"]
SUMMARY_SECTION = ["total_net", "total_vat", "total_gross"]
HEADER_PREFIX = "Section: Header."
ITEM_PREFIX = "Section: Items."
SUMMARY_PREFIX = "Section: Summary."


@dataclass
class ChunkSpec:
    section_type: str  # header | items | summary
    source_text: str  # złożony tekst (Key-Value), który posłużył do wygenerowania wektora. Zwracany do LLMa jako kontekst.
    payload: dict[str, object]  # pole metadanych do payloadu Qdrant


def build_chunks(
    structured_data: StructuredData,
    document_id: str,
    filename: str,
    chunk_max_tokens: int = settings.CHUNK_MAX_TOKENS,
) -> list[ChunkSpec]:
    base_payload = {
        "document_id": document_id,
        "filename": filename,
        "invoice_no": structured_data.invoice_no,
        "date": structured_data.date,
        "buyer": structured_data.buyer,
        "seller": structured_data.seller,
        "currency": structured_data.currency,
        "total_net": structured_data.total_net,
        "total_vat": structured_data.total_vat,
        "total_gross": structured_data.total_gross,
    }
    chunks: list[ChunkSpec] = []

    # Build header chunk
    header_text = _build_header_text(structured_data)
    if len(header_text.split()) > chunk_max_tokens:
        logger.warning(f"Header text is too long: {len(header_text.split())} tokens")
    if header_text:
        chunks.append(
            ChunkSpec(
                section_type="header",
                source_text=header_text,
                payload={k: v for k, v in base_payload.items() if v is not None},
            )
        )

    # Build items chunks
    items_lines = _build_items_lines(structured_data)
    items_chunks = _pack_items_into_chunks(items_lines, chunk_max_tokens)
    for item_chunk in items_chunks:
        chunks.append(
            ChunkSpec(
                section_type="items",
                source_text=item_chunk,
                payload={k: v for k, v in base_payload.items() if v is not None},
            )
        )

    # Build summary chunk
    summary_text = _build_summary_text(structured_data)
    if summary_text:
        chunks.append(
            ChunkSpec(
                section_type="summary",
                source_text=summary_text,
                payload={k: v for k, v in base_payload.items() if v is not None},
            )
        )

    for chunk in chunks:
        chunk.payload["section_type"] = chunk.section_type
        chunk.payload["source_text"] = chunk.source_text
    return chunks


def _build_header_text(structured_data: StructuredData) -> str:
    source_text = [HEADER_PREFIX]
    for label in HEADER_SECTION:
        val = getattr(structured_data, label, None)
        if val is not None:
            source_text.append(f"{label}: {val}")
    if len(source_text) == 1:
        return ""
    return "\n".join(source_text)


def _build_items_lines(structured_data: StructuredData) -> list[str]:
    if structured_data.items is None:
        return []
    items_lines = []
    for item in structured_data.items:
        item_line = _format_item(item)
        if item_line.strip():
            items_lines.append(item_line)
    return items_lines


def _format_item(item: InvoiceItem) -> str:
    parts: list[str] = []
    if item.item_name:
        parts.append(f"Item_name: {item.item_name}.")
    if item.quantity is not None:
        parts.append(f"Quantity: {item.quantity}.")
    if item.unit_price is not None:
        parts.append(f"Unit_price: {item.unit_price}.")
    if item.total_line_net is not None:
        parts.append(f"Total_line_net: {item.total_line_net}.")
    if item.total_line_gross is not None:
        parts.append(f"Total_line_gross: {item.total_line_gross}.")

    return "\n".join(parts)


def _build_summary_text(structured_data: StructuredData) -> str:
    source_text = [SUMMARY_PREFIX]
    for label in SUMMARY_SECTION:
        val = getattr(structured_data, label, None)
        if val is not None:
            source_text.append(f"{label}: {val}.")
    if len(source_text) == 1:
        return ""
    return "\n".join(source_text)


def _pack_items_into_chunks(item_lines: list[str], max_tokens: int) -> list[str]:
    if not item_lines:
        return []

    item_prefix_tokens = len(ITEM_PREFIX.split())
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_tokens = item_prefix_tokens

    for line in item_lines:
        line_tokens = len(line.split())
        if current_chunk and current_tokens + line_tokens > max_tokens:
            chunks.append(ITEM_PREFIX + "\n" + "\n".join(current_chunk))
            current_chunk = [line]
            current_tokens = item_prefix_tokens + line_tokens
        else:
            current_chunk.append(line)
            current_tokens += line_tokens

    if current_chunk:
        chunks.append(ITEM_PREFIX + "\n" + "\n".join(current_chunk))

    return chunks
