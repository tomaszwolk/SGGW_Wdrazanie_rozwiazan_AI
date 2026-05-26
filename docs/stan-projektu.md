# Stan projektu — OCR/VLM RAG API

Ostatnia aktualizacja: 2026-05-26 (manifesty K8s 01–04, LoadBalancer :8000, deploy-k8s.sh).

---

## Co zostało wykonane

### Faza 1 — fundament

- Struktura `app/` zgodna z `project-structure.md`
- Zależności (`uv`): FastAPI, SQLModel, Qdrant, sentence-transformers, httpx, tenacity, openai, loguru, python-multipart
- `app/core/config.py` — `Settings` + `.env` / `.env.example`, `APP_NAMESPACE` (UUID5 dla ID punktów Qdrant)
- `lifespan` w `main.py` — katalogi `data/`, `uploads`, `init_db()`, `SentenceTransformer` w `app.state.embedder`, Qdrant `ensure_collection()` + `app.state.qdrant_client`
- `GET /health` — `app/api/health.py`, SQLite + Qdrant, `HealthResponse`, HTTP 500 przy błędzie DB

### Faza 2 — warstwa danych

- **SQLite:** model `Document`, statusy (`DocumentStatus`), `get_session`, `get_document`, `check_sqlite`, `find_completed_documents_*` (hybrid RAG)
- **Qdrant:** kolekcja 384 / Cosine, `point_id`, `delete_by_document_id`, `upsert_chunks` (batch), `search_vectors` (`query_points`), `health_check`

### Faza 3–4 — dokumenty + RAG

| Element                           | Stan                                                                     |
| --------------------------------- | ------------------------------------------------------------------------ |
| `POST /documents/upload`          | 202, walidacja w `upload_validation.py`                                  |
| `BackgroundTasks` + `vlm_service` | OpenRouter, vision, retry, JSON schema                                   |
| `GET /documents/{id}`             | 200; dane tylko przy `completed`                                         |
| `app/utils/text_processing.py`    | `ChunkSpec`, header / items / summary, pack items po produktach          |
| `POST /documents/{id}/index`      | 404 / 409 / 500, `IndexResponse`, `index_document()`                     |
| `POST /documents/index-all`       | 202, bulk index w tle                                                    |
| `POST /rag/search`                | `hybrid_search`, `enrich_search_results_with_sqlite`, `SearchResultItem` |
| `POST /rag/answer`                | jak search + LLM; `sources: list[SearchResultItem]`                      |
| Routery                           | `documents`, `rag`, `health` — podpięte w `main.py`                      |

### Faza 5 — Docker

- **`Dockerfile`** (multi-stage builder/runtime), **`.dockerignore`**
- PyTorch **CPU-only** (`torch` z indeksu pytorch.org/whl/cpu w `pyproject.toml` + `uv.lock`)
- Pre-cache **`all-MiniLM-L6-v2`** przy buildzie
- Obraz lokalny: **`ocr-rag-api:latest`** (~2.2 GB)
- Publikacja opcjonalna: **[`tomaszwolk/ocr-rag-api`](https://hub.docker.com/r/tomaszwolk/ocr-rag-api)** — opis w README (sekcja Docker), **nie** domyślna ścieżka K8s
- README: build, run z volume `./data`, `QDRANT_HOST=host.docker.internal`, diagram Mermaid przepływu, modele VLM/LLM

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

- **`invoice_no`** w JSON z VLM; **`Document.filename`** w SQLite = nazwa z uploadu; w Qdrant payload **`filename`**.
- Pozycje: **`total_line_net`** / **`total_line_gross`**.
- W chunkach **pomijamy `None`**; audyt pełnych danych → `GET /documents/{id}`.

### Chunking (`text_processing.py`)

- **header / summary** — jeden chunk; **items** — jeden produkt = jeden blok, pakowanie po `CHUNK_MAX_TOKENS`.
- Etykiety w **`source_text` po angielsku** (faktury testowe angielskie).

### Qdrant i indeksowanie

- Przed `upsert` → **`delete_by_document_id`**.
- ID punktów: **UUID5**(`APP_NAMESPACE`, `{document_id}:{section_type}:{index}`).
- Wyszukiwanie: **`query_points`** → **`SearchResultItem`**.

### RAG / LLM (answer)

- **Hybrid search** — regex/kotwice w pytaniu + `LIKE` na `structured_data` (max 3 dokumenty, `sql_match` na końcu listy).
- **`metadata.entire_document`** na każdym hicie; do LLM pełny JSON tylko przy max `score` per `document_id`.
- Brak wyników → `"No information available"` bez LLM.
- **Modele (testy):** VLM `openai/gpt-4o-mini`, LLM `deepseek/deepseek-v4-flash` (OpenRouter).

### API

- Embedder i Qdrant z **`request.app.state`**.
- `top_k` domyślnie z `RAG_DEFAULT_TOP_K`; `0` / brak w Swagger → wartość z `.env`.

### VLM

- OpenRouter, retry bez `400`; po sukcesie — usunięcie pliku obrazu z dysku.

### BackgroundTasks (świadomy trade-off)

- **Bez Celery + Redis** — mniej komponentów, wystarczające na zaliczenie (upload VLM + `/index-all`).
- **Konsekwencja w K8s/Docker:** restart poda/kontenera **przerywa** zadanie w tle (VLM, bulk index); po restarcie trzeba ponowić upload/index jeśli proces się urwał.
- **Nie** mieszać `--reload` z zadaniami w tle (dev).

---

## Co zostało do wykonania — Kubernetes (Faza 6)

Szczegóły planu: [docs/k8s-plan.md](k8s-plan.md). Manifesty: **`k8s/01`–`04`** (gotowe).

### Decyzje na implementację K8s (ustalone 2026-05-22)

| Temat            | Decyzja                                                                                                                                                                                                                                                        |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Obraz API**    | Domyślnie Hub `tomaszwolk/ocr-rag-api:latest`, `IfNotPresent`. `./scripts/deploy-k8s.sh --local` → build + import + `ocr-rag-api:latest`.                                                                                                                      |
| **Konfiguracja** | Jedno źródło: **`.env`**. Skrypt → ConfigMap (jawne + nadpisania K8s) + Secret (`OPENROUTER_API_KEY` tylko).                                                                                                                                                   |
| **Probes**       | `livenessProbe` + `readinessProbe` → HTTP GET **`/health:8000`** (kod bez zmian). API nie będzie Ready dopóki Qdrant nie działa — oczekiwane; kolejność apply: Qdrant przed API. `initialDelaySeconds` / `startPeriodSeconds` ~120–180s (ładowanie embeddera). |
| **RAM**          | **Bez sztywnych limitów** w manifestach (jeśli limit powoduje OOM). W README: **wymagania minimalne** dla maszyny (np. ~4 GB RAM wolne dla API+Qdrant+OS, orientacyjnie).                                                                                      |
| **Storage**      | PVC `sqlite-data-pvc` (1Gi) → `/app/data`, PVC `qdrant-data-pvc` (2Gi) → Qdrant.                                                                                                                                                                               |
| **Dostęp**       | `api-service` **LoadBalancer :8000** → http://localhost:8000 (jak dev)                                                                                                                                                                                         |
| **ConfigMap**    | `QDRANT_HOST=qdrant-service`, ścieżki `/app/data/...`, modele jak w `.env.example`                                                                                                                                                                             |

### Checklist implementacji

1. [x] `01-namespace.yaml` — `ai-rag-app`
2. [x] ConfigMap `app-config` — generowany z `.env` przez `scripts/deploy-k8s.sh` (nadpisania K8s)
3. [x] Secret `app-secrets` — tylko `OPENROUTER_API_KEY` ze skryptu (nie commitować)
4. [x] `02-storage.yaml` — 2× PVC
5. [x] `03-qdrant.yaml` — Deployment + Service ClusterIP
6. [x] `04-api.yaml` — Deployment + LoadBalancer :8000, envFrom, probes, mount PVC
7. [x] Test: `/health`, `/docs`, E2E upload → index → answer
8. [x] README — sekcja Kubernetes (komendy, secret, wymagania RAM, notka Hub, BackgroundTasks w K8s)

---

## Na przyszłość — rzeczy do monitorowania

| Temat                                 | Uwaga                                                                |
| ------------------------------------- | -------------------------------------------------------------------- |
| **`currency: null`**                  | Czasem brak waluty w JSON mimo symbolu w `raw_text`.                 |
| **`response_format` + `strict`**      | Przy zmianie `VLM_MODEL_NAME` testuj jednym uploadem.                |
| **Retry VLM/LLM**                     | Nie ponawiać `400`.                                                  |
| **Restart poda**                      | BackgroundTasks — VLM/index-all mogą się urwać.                      |
| **SQLite vs Qdrant**                  | Ten sam klaster K8s + PVC; nie mieszać ze starym Qdrantem na hoście. |
| **Agregacje RAG** („najwyższa kwota”) | Poza scope — czysty RAG nie agreguje po wszystkich fakturach.        |

---

## Stan plików (skrót)

| Gotowe                                       | Do zrobienia         |
| -------------------------------------------- | -------------------- |
| `app/` (API, serwisy, db, utils)             | test E2E na klastrze |
| `Dockerfile`, `.dockerignore`, `k8s/01`–`05` |                      |
| `README` (Docker, K8s, E2E, decyzje)         |                      |
| `docs/k8s-plan.md`                           |                      |

---

## Następna sesja

1. `./scripts/deploy-k8s.sh` → test http://localhost:8000/health + E2E.
