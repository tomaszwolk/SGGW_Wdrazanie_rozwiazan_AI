# Stan projektu — OCR/VLM RAG API

Ostatnia aktualizacja: 2026-05-21 (po ukończeniu etapu upload + VLM).

---

## Co zostało wykonane

### Faza 1 — fundament

- Struktura `app/` zgodna z `project-structure.md`
- Zależności (`uv`): FastAPI, SQLModel, Qdrant, sentence-transformers, httpx, tenacity, openai, loguru, python-multipart
- `app/core/config.py` — `Settings` + `.env` / `.env.example`
- `lifespan` w `main.py` — katalogi `data/`, `uploads`, `init_db()`, Qdrant `ensure_collection()`
- `GET /health` — SQLite + Qdrant, `HealthResponse`, HTTP 500 przy błędzie DB

### Faza 2 — warstwa danych

- **SQLite:** model `Document`, statusy (`DocumentStatus`), `get_session`, `get_document`, `check_sqlite`
- **Qdrant:** klient, kolekcja 384 / Cosine, `health_check`, `app.state.qdrant_client`
- Obsługa wyjątków (węższe typy zamiast ślepego `Exception` tam, gdzie to poprawiano)

### Faza 3–4 (część dokumentów) — ukończony vertical slice

| Element | Stan |
|--------|------|
| `POST /documents/upload` | 202, walidacja w `upload_validation.py` (suffix + content-type) |
| Zapis pliku | `data/uploads/{document_id}.{suffix}` |
| Rekord SQLite | `queued` → `processing` → `completed` / `failed` |
| `BackgroundTasks` | `process_document_vlm` z osobną sesją, loguru |
| `vlm_service.py` | OpenRouter przez OpenAI SDK, vision, retry, JSON schema (bez `strict` po błędzie Azure) |
| `GET /documents/{id}` | 200; dane tylko przy `completed` |
| Po sukcesie VLM | usunięcie pliku obrazu z dysku |

### Poprawki po testach (świadome decyzje)

- **`invoice_no`** w `StructuredData` zamiast `filename` w JSON; **`documents.filename`** = nazwa z uploadu (SQL)
- Usunięte nadpisywanie `structured_data` nazwą pliku w `background_tasks`
- Pozycje faktury: **`total_line_net`** / **`total_line_gross`** zamiast jednego niejednoznacznego `total_price`
- Debug: detached ORM w tle, `strict` + schema OpenRouter, retry na 400 — rozwiązane

### Zweryfikowany flow (E2E)

```
POST /upload → 202
→ log: VLM started → VLM completed (~10 s)
→ GET /documents/{id} → status: completed, raw_text + structured_data
```

---

## Co zostało do wykonania (kolejność z planu)

### Faza 3 — reszta logiki biznesowej

1. **`app/utils/text_processing.py`** — chunking: header / items / summary, Key-Value, limit `CHUNK_MAX_TOKENS`
2. **`app/db/qdrant.py`** — rozszerzenie: `delete_by_document_id`, `upsert_chunks`, `search`
3. **`app/services/rag_service.py`** — singleton embeddingów (MiniLM), `index_document`, `search`, `answer` (LLM + prompt księgowy z PRD)
4. **`app/models/schemas.py`** — modele pod search/answer (`SearchRequest`, `AnswerResponse`, …)

### Faza 4 — API RAG

5. **`POST /documents/{document_id}/index`** — 409 jeśli ≠ `completed`, zapis wektorów + payload (w payloadzie `filename` z **SQLite**, nie `invoice_no`)
6. **`POST /rag/search`** i **`POST /rag/answer`**
7. Podpięcie routerów w `main.py` (rag już jako plik — do wypełnienia)

### Faza 5–7 — zaliczenie / wdrożenie

8. **Dockerfile**, `.dockerignore`, build `ocr-rag-api:latest`
9. **Kubernetes** — `k8s/01`–`05`, NodePort 30080
10. **README** — deploy, BackgroundTasks vs Celery, pytania teoretyczne o Docker

### Testowy scenariusz końcowy (z planu)

```
upload → poll GET → index → search → answer
```

---

## Na przyszłość — rzeczy do monitorowania

| Temat | Uwaga |
|--------|--------|
| **`currency: null`** | Czasem w JSON brak waluty mimo `$` / `PLN` w `raw_text`. Przy RAG można: doprecyzować prompt VLM, post-processing z regex na `raw_text`, lub uzupełniać przy indeksowaniu z payloadu. |
| **`invoice_no`** | `str \| None` — OK dla formatów alfanumerycznych. Przy braku numeru na skanie walidacja Pydantic / status `failed` — świadoma polityka (nie `unknown` w prompcie). |
| **`response_format` + `strict`** | Modele przez OpenRouter (np. Azure) różnie traktują schema; przy zmianie `VLM_MODEL_NAME` testuj jednym uploadem. |
| **Retry** | Nie ponawiać `400` / `BadRequestError` (schema, zły model). |
| **`--reload`** | Przy dev upload tuż po zapisie pliku — task może zginąć; na test E2E krótko bez reload lub poczekać na stabilny proces. |
| **OpenRouter „usage”** | Failed requesty mogą nie być widoczne jak sukcesy — patrz Activity/Logs, nie tylko licznik klucza. |
| **PRD vs `db-plan` payload** | W Qdrant nadal pole `filename` (nazwa pliku z uploadu); w JSON faktury jest `invoice_no` — nie mieszać przy chunkingu. |
| **GET przy `failed`** | `error_message` w odpowiedzi; `raw_text` / `structured_data` = null (zgodnie z api-plan). |
| **Stare dokumenty w SQLite** | Po zmianie schema (`invoice_no`, `line_net`/`gross`) stare rekordy JSON mogą nie przejść `model_validate_json` — tylko nowe uploady albo re-upload. |
| **RAM / K8s** | Singleton modelu embeddingów w `lifespan`; limit 1 Gi na pod API. |

---

## Stan plików (skrót)

| Gotowe / w użyciu | Szkielet / TODO |
|-------------------|----------------|
| `config`, `main`, `domain`, `schemas` (health + dokumenty) | `text_processing.py` |
| `sqlite`, `qdrant` (init + health) | `rag_service.py` |
| `documents.py`, `upload_validation` | `api/rag.py` |
| `vlm_service`, `background_tasks` | `Dockerfile`, `k8s/`, README |

---

## Następna sesja — sensowny start

1. `text_processing.py` (najprostszy krok bez zewnętrznych API)
2. `index` + rozszerzenie `qdrant.py`
3. `rag_service` + `/rag/search` + `/rag/answer`
