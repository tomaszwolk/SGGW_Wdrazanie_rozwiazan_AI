# Architektura — OCR/VLM RAG API

Dokument uzupełnia [README.md](../README.md): przepływy, schematy Pydantic i szczegóły implementacji. Nie zastępuje instrukcji uruchomienia.

---

## Przepływ end-to-end (poziom systemu)

Jeden diagram „od pliku do odpowiedzi” — czytelny na pierwszy rzut oka:

```mermaid
flowchart LR
  IMG["Obraz .jpg/.png"] --> UP["POST /documents/upload"]
  UP -.->|BackgroundTasks| VLM["VLM — OpenRouter"]
  VLM --> SQL[("SQLite — status, JSON")]
  SQL --> IDX["POST .../index lub /index-all"]
  IDX --> QD[("Qdrant — wektory")]
  QD --> SRCH["POST /rag/search"]
  QD --> ANS["POST /rag/answer"]
  ANS --> LLM["LLM — OpenRouter"]
  SRCH --> OUT1["Fragmenty + metadane"]
  ANS --> OUT2["Odpowiedź + sources"]
```

**Startup** (przed ruchem API): `init_db` → `SentenceTransformer` w `app.state.embedder` → klient Qdrant + `ensure_collection` (`app/main.py` lifespan).

---

## Warstwy kodu

```mermaid
flowchart TB
  subgraph API["app/api — routery FastAPI"]
    health[health.py]
    docs[documents.py]
    rag[rag.py]
  end
  subgraph SVC["app/services"]
    vlm[vlm_service.py]
    rags[rag_service.py]
    bg[background_tasks.py]
  end
  subgraph DATA["app/db + utils"]
    sqlite[sqlite.py]
    qdrant[qdrant.py]
    chunk[text_processing.py]
    valid[upload_validation.py]
  end
  API --> SVC
  SVC --> DATA
  API --> DATA
```

Walidacja wejścia i kształty odpowiedzi: **`app/models/schemas.py`** (Pydantic). Encja dokumentu w bazie: **`app/models/domain.py`** (SQLModel).

---

## Dokumenty — upload, status, indeks

```mermaid
flowchart TB
  subgraph UPLOAD["POST /documents/upload"]
    U1[validate_upload_file] --> U2["SQLite: queued"]
    U2 -.-> U3[process_document_vlm]
    U3 --> U4[extract_structured_data]
    U4 --> U5["SQLite: completed / failed"]
    U5 --> U6[usuń plik z UPLOAD_DIR]
  end
```

```mermaid
flowchart TB
  subgraph GET["GET /documents/{id}"]
    G1[get_document] --> G2[DocumentDetailResponse]
  end
```

```mermaid
flowchart TB
  subgraph INDEX["POST /documents/{document_id}/index"]
    I1[index_document] --> I2[build_chunks]
    I2 --> I3[delete_by_document_id]
    I3 --> I4[embedder.encode + upsert_chunks]
  end
```

`POST /documents/index-all` — ten sam łańcuch co wyżej (`index_document`), wywoływany w pętli w tle:

```mermaid
flowchart TB
  subgraph BULK["POST /documents/index-all"]
    A1[list_completed_document_ids] -.-> A2[index_all_completed_documents]
    A2 -.-> LOOP["dla każdego ID: index_document()"]
  end
```

Statusy dokumentu (`DocumentStatus`): `queued` → `processing` → `completed` lub `failed`.

---

## RAG — wyszukiwanie i odpowiedź

```mermaid
flowchart TB
  subgraph SEARCH["POST /rag/search"]
    R1[hybrid_search] --> R2[search_documents — Qdrant]
    R1 --> R3[SQLite LIKE po numerze faktury]
    R2 --> R4[merge + enrich_search_results_with_sqlite]
    R3 --> R4
    R4 --> R5[SearchResponse]
  end
```

```mermaid
flowchart TB
  subgraph ANSWER["POST /rag/answer"]
    Q1[hybrid_search] --> Q2[enrich...]
    Q2 --> Q3{wyniki puste?}
    Q3 -->|tak| Q4["No information available"]
    Q3 -->|nie| Q5[answer_question — LLM]
    Q5 --> Q6[AnswerResponse + sources]
  end
```

---

## Pydantic — główne modele

| Model                                                 | Rola                 |
| ----------------------------------------------------- | -------------------- |
| `StructuredData`, `InvoiceItem`                       | JSON z VLM (faktura) |
| `UploadResponse`, `DocumentDetailResponse`            | Upload i status      |
| `IndexResponse`, `BulkIndexResponse`                  | Indeksowanie         |
| `SearchRequest`, `SearchResponse`, `SearchResultItem` | `/rag/search`        |
| `AnswerRequest`, `AnswerResponse`                     | `/rag/answer`        |
| `HealthResponse`                                      | `/health`            |

FastAPI automatycznie zwraca **422** przy niepoprawnym body (np. brak pola `query`). Upload zły format pliku → **400** (`validate_upload_file`).

Szczegóły pól: `app/models/schemas.py`.

---

## JSON strukturalny (VLM → SQLite)

Wynik ekstrakcji to `StructuredData` (zapisany jako JSON w kolumnie `structured_data`). Przykładowy kształt:

```json
{
  "invoice_no": "INV-2024-001",
  "date": "2024-03-15",
  "buyer": "Acme Corp",
  "seller": "Supplier Ltd",
  "currency": "USD",
  "total_net": 1000.0,
  "total_vat": 230.0,
  "total_gross": 1230.0,
  "items": [
    {
      "item_name": "Widget A",
      "quantity": 2,
      "unit_price": 500.0,
      "total_line_net": 1000.0,
      "total_line_gross": 1230.0
    }
  ]
}
```

Pola opcjonalne (`null` w JSON) — w chunkach do embeddingu **pomijane**, pełny audyt przez `GET /documents/{document_id}`.

Dodatkowo w SQLite: `raw_text` (tekst z VLM), `filename` (nazwa pliku z uploadu). W Qdrant w payloadzie m.in. `filename`, `section_type`, `source_text`.

---

## Modele OpenRouter

| Rola                   | Zmienna `.env`   | Model (testy)                | Uwagi                                           |
| ---------------------- | ---------------- | ---------------------------- | ----------------------------------------------- |
| VLM (OCR / ekstrakcja) | `VLM_MODEL_NAME` | `openai/gpt-4o-mini`         | Tańsze modele gorzej wypełniały pola na skanach |
| LLM (RAG answer)       | `LLM_MODEL_NAME` | `deepseek/deepseek-v4-flash` | Q&A na kontekście chunków; niski koszt          |

Wartości w `.env` / `.env.example`.
