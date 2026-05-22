# OCR/VLM RAG API — zaliczenie SGGW

REST API (FastAPI): upload skanów faktur → ekstrakcja VLM (OpenRouter) → indeks wektorowy (Qdrant) → wyszukiwanie i odpowiedzi RAG (lokalne embeddingi + LLM).

**Szczegółowy stan kodu:** [docs/stan-projektu.md](docs/stan-projektu.md)  
**Plany:** [docs/prd.md](docs/prd.md), [docs/api-plan.md](docs/api-plan.md), [docs/db-plan.md](docs/db-plan.md), [docs/k8s-plan.md](docs/k8s-plan.md)

---

## Wymagania

- Python 3.12+, [uv](https://docs.astral.sh/uv/)
- Działający **Qdrant** (lokalnie, np. Docker: `docker run -p 6333:6333 qdrant/qdrant`)
- Klucz **OpenRouter** w `.env` (VLM + LLM)
- Do wdrożenia K8s: Docker Desktop z Kubernetes, `kubectl`

---

## Uruchomienie lokalne (dev)

```bash
cp .env.example .env
# uzupełnij OPENROUTER_API_KEY

uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Swagger: http://localhost:8000/docs  
- Health: http://localhost:8000/health  

W K8s ścieżki danych to `/app/data` (PVC); lokalnie domyślnie `./data/` (SQLite, uploady).

### Scenariusz testowy (E2E)

1. `POST /documents/upload` — plik `.jpg` / `.png`
2. `GET /documents/{id}` — poll aż `status: completed`
3. `POST /documents/{id}/index` — wektory w Qdrant
4. `POST /rag/search` — body: `{"query": "...", "top_k": 3}`
5. `POST /rag/answer` — body: `{"question": "...", "top_k": 3}`

Przy `--reload` zadanie VLM w tle może się urwać — na pełny E2E lepiej bez reload.

---

## Docker (do uzupełnienia po dodaniu Dockerfile)

> Po utworzeniu `Dockerfile` i `.dockerignore` uzupełnij tę sekcję konkretnymi komendami z Twojego pliku.

```bash
docker build -t ocr-rag-api:latest .
```

Obraz docelowy: `ocr-rag-api:latest`, port **8000**, wolumen na dane: `/app/data`.

---

## Kubernetes (do uzupełnienia po dodaniu `k8s/`)

> Manifesty wg [docs/k8s-plan.md](docs/k8s-plan.md), namespace `ai-rag-app`.

Kolejność:

```bash
kubectl apply -f k8s/01-namespace.yaml
kubectl apply -f k8s/02-config.yaml
kubectl apply -f k8s/03-storage.yaml
kubectl apply -f k8s/04-qdrant.yaml
kubectl apply -f k8s/05-api.yaml
```

API z hosta (Docker Desktop): http://localhost:30080/health  

Secret `OPENROUTER_API_KEY` — w manifeście Base64 lub `kubectl create secret` (nie commituj prawdziwego klucza).

---

## Dlaczego `BackgroundTasks`, a nie Celery/Redis?

| | **FastAPI BackgroundTasks** | **Celery + Redis** |
|---|---------------------------|-------------------|
| Infrastruktura | Brak kolejki — ten sam proces co API | Osobny broker (Redis/RabbitMQ) i worker(y) |
| Złożoność | Niska — wystarczy na VLM po uploadzie | Wyższa — kolejki, monitoring workerów |
| Skalowanie | Jedna replika API; długie VLM obciąża ten sam pod | Wiele workerów, rozłożenie zadań |
| Trwałość zadań | Zadanie ginie przy restarcie procesu | Kolejka przetrwa restart workera |
| Ten projekt | Jedna faktura → jedno zadanie w tle, zaliczenie lokalne/K8s | Przydatne przy dużym wolumenie i SLA |

**Wniosek:** Dla zaliczenia i lokalnego K8s BackgroundTasks to świadomy trade-off: prostsze wdrożenie, mniej komponentów. Celery ma sens przy masowym OCR i oddzielnym skalowaniu workerów.

---

## Decyzje projektowe (pamiętaj przy obronie / rozwoju)

### Język promptów i chunków

**Prompty VLM/LLM oraz etykiety w chunkach (`Section: Header.`, `Item_name:`, …) są po angielsku** — świadoma decyzja: przykładowe faktury w bazie testowej są angielskie; planowane testy mniejszych modeli, które gorzej radzą sobie z polskim w promptach. API może przyjmować pytania po polsku — embeddingi i LLM i tak operują na angielskim kontekście z indeksu.

### SQLite vs Qdrant

- **SQLite** — stan dokumentu (`queued` → `completed`), `raw_text`, JSON `structured_data`.
- **Qdrant** — wektory chunków + payload (`document_id`, `section_type`, `source_text`, metadane faktury).
- **`document_id`** (UUID) łączy obie bazy. ID **punktu** w Qdrant: UUID5 z `APP_NAMESPACE` i klucza `{document_id}:{section_type}:{index}`.

### Indeksowanie i re-indeksacja

Przed każdym `POST .../index` dla dokumentu: **`delete_by_document_id`** (filtr po `document_id` w payload), potem batch **`upsert`**. Powód: liczba chunków `items` zależy od długości listy produktów — sam upsert zostawiałby stare punkty („zombie”). Losowe UUID v4 na chunki nie są potrzebne przy tym podejściu.

### Chunking

- **Header / summary** — zwykle jeden chunk; bez dzielenia po tokenach.
- **Items** — jeden produkt = jeden sformatowany blok; łączenie w chunki do limitu `CHUNK_MAX_TOKENS`; brak cięcia w środku produktu.
- W tekście chunka **pomijamy pola `None`** (nie wstawiamy `"None"` do embeddingów).

### Pola faktury

- W JSON z VLM: **`invoice_no`** (nie mylić z nazwą pliku).
- **`Document.filename`** w SQLite = nazwa z uploadu; to samo w payloadzie Qdrant jako **`filename`**.
- Pozycje: **`total_line_net`**, **`total_line_gross`**.

### RAG `/answer`

- Wyszukiwanie jak `/search`, potem kontekst przez **`_format_answer_context()`** (fragmenty `--- Fragment N (document_id: ...) ---`, nie repr listy Pythona).
- **`AnswerSource`** w odpowiedzi — tylko `document_id` + `source_text` (wężej niż `SearchResultItem` ze score/metadata).
- Brak wyników search → odpowiedź `"No information available"` **bez** wywołania LLM.

### VLM (OpenRouter)

- Retry (`tenacity`) na błędy sieciowe / rate limit — **nie** ponawiać `400` (zły schema/model).
- `response_format` bez `strict` tam, gdzie provider odrzuca schema.
- Po sukcesie — **usunięcie pliku obrazu** z dysku.

### API

- Embedder (`SentenceTransformer`) i klient Qdrant — **`app.state`** w `lifespan`, używane w routerach przez `Request`.
- Qdrant search: **`query_points`** (nowsze API klienta), nie przestarzałe `search()`.

---

## Pytania teoretyczne — Docker (wymaganie zaliczenia)

### Czym jest Dockerfile?

Plik tekstowy z instrukcjami budowy **obrazu** kontenera (bazowy obraz, instalacja zależności, kopiowanie kodu, `CMD`/`ENTRYPOINT`). `docker build` wykonuje te kroki i tworzy niezmienną „matrycę” do uruchamiania kontenerów.

### Czym jest `.dockerignore`?

Odpowiednik `.gitignore` dla **kontekstu buildu** — pliki/katalogi nie trafiają do demona Dockera przy `docker build`. Mniejszy kontekst = szybszy build i brak sekretów / `.venv` w obrazie.

### Czym jest docker context?

Zestaw plików wysyłanych do Dockera podczas buildu (zwykle katalog z Dockerfile + `.dockerignore`). Tylko to, co w kontekście, może być skopiowane instrukcją `COPY`.

### Jak działają warstwy obrazu (image layers)?

Każda instrukcja Dockerfile (RUN, COPY, …) tworzy **warstwę** (cache’owaną). Warstwy są tylko do odczytu i współdzielone między obrazami. Zmiana wczesnej warstwy unieważnia cache późniejszych kroków.

### Jak zoptymalizować czas budowy obrazu?

- Rzadko zmieniane kroki **na górę** (baza, `uv sync` / instalacja zależności).
- Kod aplikacji **`COPY` na dół**.
- `.dockerignore` (bez `.venv`, `docs`, `.git`).
- Łączenie RUN w jedną warstwę tam, gdzie ma sens.
- Multi-stage build (build deps vs runtime) — mniejszy finalny obraz.

### Dlaczego kolejność instrukcji w Dockerfile ma znaczenie?

Bo **cache warstw** — jeśli zmienisz plik źródłowy, warstwa `COPY` i wszystko po niej buduje się od nowa. Gdy zależności są zainstalowane wcześniej, przy zmianie tylko kodu nie pobierasz ponownie całego PyTorch/sentence-transformers.

---

## Struktura repozytorium (skrót)

```
app/
  api/          documents, rag, health
  services/     vlm_service, rag_service, background_tasks
  db/           sqlite, qdrant
  utils/        text_processing, upload_validation
  models/       domain, schemas
  core/         config
data/           SQLite, uploady (lokalnie; PVC w K8s)
docs/           plany i stan-projektu.md
k8s/            (do dodania) manifesty YAML
```

---

## Co jeszcze zrobić przed oddaniem

- [ ] `Dockerfile` + `.dockerignore` → uzupełnij sekcję Docker powyżej
- [ ] `k8s/01`–`05` → uzupełnij sekcję Kubernetes
- [ ] Test na klastrze: `http://localhost:30080/health` + pełny flow E2E
