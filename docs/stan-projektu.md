# Stan projektu — OCR/VLM RAG API



Ostatnia aktualizacja: 2026-05-22 (API RAG domknięte, `/health` w `api/health.py`).



---



## Co zostało wykonane



### Faza 1 — fundament



- Struktura `app/` zgodna z `project-structure.md`

- Zależności (`uv`): FastAPI, SQLModel, Qdrant, sentence-transformers, httpx, tenacity, openai, loguru, python-multipart

- `app/core/config.py` — `Settings` + `.env` / `.env.example`, `APP_NAMESPACE` (UUID5 dla ID punktów Qdrant)

- `lifespan` w `main.py` — katalogi `data/`, `uploads`, `init_db()`, `SentenceTransformer` w `app.state.embedder`, Qdrant `ensure_collection()` + `app.state.qdrant_client`

- `GET /health` — `app/api/health.py`, SQLite + Qdrant, `HealthResponse`, HTTP 500 przy błędzie DB



### Faza 2 — warstwa danych



- **SQLite:** model `Document`, statusy (`DocumentStatus`), `get_session`, `get_document`, `check_sqlite`

- **Qdrant:** kolekcja 384 / Cosine, `point_id`, `delete_by_document_id`, `upsert_chunks` (batch), `search_vectors` (`query_points`), `health_check`



### Faza 3–4 — dokumenty + RAG



| Element | Stan |

|--------|------|

| `POST /documents/upload` | 202, walidacja w `upload_validation.py` |

| `BackgroundTasks` + `vlm_service` | OpenRouter, vision, retry, JSON schema |

| `GET /documents/{id}` | 200; dane tylko przy `completed` |

| `app/utils/text_processing.py` | `ChunkSpec`, header / items / summary, pack items po produktach |

| `POST /documents/{id}/index` | 404 / 409 / 500, `IndexResponse`, `index_document()` |

| `POST /rag/search` | body `SearchRequest`, `SearchResponse` + `SearchResultItem` |

| `POST /rag/answer` | body `AnswerRequest`, `AnswerResponse` + `sources: list[SearchResultItem]`, `metadata.entire_document`, `_format_answer_context()` |

| Routery | `documents`, `rag`, `health` — podpięte w `main.py` |



### Zweryfikowane flow (E2E)



```

POST /upload → 202

→ GET /documents/{id} → completed

→ POST /documents/{id}/index → 200, chunks_indexed > 0

→ POST /rag/search → 200

→ POST /rag/answer → 200 (answer + sources)

```



Wielokrotne `index` na tym samym dokumencie — bez duplikatów (delete przed upsert).



---



## Decyzje architektoniczne (notatki pod README)



### Dane i modele



- **`invoice_no`** w JSON z VLM; **`Document.filename`** w SQLite = nazwa z uploadu; w Qdrant payload **`filename`** (nie `invoice_no`).

- Pozycje: **`total_line_net`** / **`total_line_gross`**.

- W chunkach **pomijamy `None`**; audyt pełnych danych → `GET /documents/{id}`.



### Chunking (`text_processing.py`)



- **`ChunkSpec`** — `@dataclass` w `text_processing.py`; `schemas.py` = kontrakty HTTP.

- **header / summary** — jeden chunk, bez token-split; **items** — jeden produkt = jeden blok, pakowanie po `CHUNK_MAX_TOKENS`.

- Etykiety w **`source_text` po angielsku** — świadoma decyzja (angielskie faktury testowe, mniejsze modele LLM później).



### Qdrant i indeksowanie



- Przed `upsert` → **`delete_by_document_id`** (re-indeksacja, brak zombie chunków `items`).

- ID punktów: **UUID5**(`APP_NAMESPACE`, `{document_id}:{section_type}:{index}`).

- Liczniki sekcji w **`upsert_chunks()`**.

- Wyszukiwanie: **`query_points`**, mapowanie → **`SearchResultItem`**.



### RAG / LLM (answer)



- **`/rag/answer` sources** — ten sam kształt co `SearchResultItem`; `metadata.entire_document` z SQLite (JSON); do LLM pełny dokument tylko przy najwyższym `score` per `document_id`.

- Kontekst LLM: **`_format_answer_context()`** (`--- Fragment N ---`, nie repr listy).

- Prompty LLM **po angielsku** (jak VLM/chunki); brak wyników search → `"No information available"` bez wywołania OpenRouter.

- OpenRouter: ten sam `OpenAI` client co VLM; retry na błędy sieciowe.



### API



- Embedder i Qdrant z **`request.app.state`**.

- `index` / `search` / `answer`: `HTTPException` 404 / 409 / 422 / 500.

- RAG: body JSON (`SearchRequest`, `AnswerRequest`).



### VLM



- OpenRouter, retry bez `400`; bez `strict` tam, gdzie model odrzuca schema.

- Po sukcesie VLM — usunięcie pliku obrazu z dysku.



---



## Co zostało do wykonania



### Faza 5–7 — zaliczenie / wdrożenie



1. **Dockerfile**, `.dockerignore`, build `ocr-rag-api:latest` — sekcje w README jako szablon

2. **Kubernetes** — `k8s/01`–`05`, NodePort 30080, probes na `/health`

3. **README** — szkielet gotowy (decyzje, teoria Docker, BackgroundTasks); po Docker/K8s uzupełnić komendy deploy



---



## Na przyszłość — rzeczy do monitorowania



| Temat | Uwaga |

|--------|--------|

| **`currency: null`** | Czasem brak waluty w JSON mimo symbolu w `raw_text`. |

| **`response_format` + `strict`** | Przy zmianie `VLM_MODEL_NAME` testuj jednym uploadem. |

| **Retry VLM/LLM** | Nie ponawiać `400` / `BadRequestError`. |

| **`--reload`** | Background task może zginąć — E2E bez reload. |

| **Stare rekordy SQLite** | Po zmianie schema JSON — re-upload. |

| **RAM / K8s** | Singleton embeddera w `lifespan`; limit 1 Gi na pod API. |

| **Indeks payload `total_gross`** | Opcjonalnie (db-plan) — nie zaimplementowane. |



---



## Stan plików (skrót)



| Gotowe | Do zrobienia |

|--------|----------------|

| `main`, `config`, `domain`, `schemas` | `Dockerfile`, `k8s/` |

| `sqlite`, `qdrant`, `text_processing` | uzupełnić README po Docker/K8s |

| `documents`, `rag`, `health` | |

| `vlm_service`, `background_tasks`, `rag_service` | |

| `upload_validation` | |



---



## Następna sesja



1. Dockerfile + `.dockerignore` → `docker build -t ocr-rag-api:latest .`

2. Manifesty K8s 01→05, test `http://localhost:30080/health`

3. Uzupełnić w README sekcje Docker/K8s po implementacji manifestów


