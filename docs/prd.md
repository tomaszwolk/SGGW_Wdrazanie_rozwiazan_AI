# PRODUCT REQUIREMENTS DOCUMENT (PRD)

## Nazwa projektu: OCR/VLM RAG API na Kubernetes

### 1. Cel projektu

Stworzenie aplikacji REST API (FastAPI), która przyjmuje obrazy dokumentów (faktury/paragony), odczytuje ich zawartość przy użyciu zewnętrznego modelu VLM (przez OpenRouter), zapisuje dane ustrukturyzowane, tworzy embeddingi i pozwala na wyszukiwanie informacji oraz zadawanie pytań (RAG) z wykorzystaniem bazy wektorowej Qdrant. Aplikacja musi być wdrożona na lokalnym klastrze Kubernetes (Docker Desktop).

### 2. Architektura i Infrastruktura

- **Język i Framework:** Python 3.12+, FastAPI, Pydantic (v2), `pydantic-settings`.
- **Baza danych (Stan):** SQLite (zapisywana na Persistent Volume). Przechowuje statusy dokumentów i wyekstrahowane dane JSON.
- **Baza wektorowa:** Qdrant (oficjalny obraz Dockerowy, osobny Deployment w K8s, dane na Persistent Volume).
- **Środowisko uruchomieniowe:** Kubernetes (lokalnie przez Docker Desktop).
- **Zarządzanie plikami:** Przesłane obrazy są zapisywane tymczasowo na PVC, a po pomyślnym przetworzeniu przez VLM są usuwane z dysku.

### 3. Modele AI i Logika Przetwarzania

- **Ekstrakcja (VLM):** Zewnętrzne API przez OpenRouter (model konfigurowalny, np. `gpt-4o-mini` lub `anthropic/claude-3-haiku`).
  - _Zadanie:_ Model ma zwrócić czysty JSON zawierający dwie sekcje: `raw_text` (cały tekst) oraz `structured_data` (pola: `invoice_no`, `date`, `buyer`, `seller`, `currency`, `total_net`, `total_vat`, `total_gross`, `items` [lista produktów z cenami: `item_name`, `quantity`, `unit_price`, `total_line_net`, `total_line_gross`]).
- **Embeddingi:** Lokalny model `sentence-transformers/all-MiniLM-L6-v2` uruchamiany wewnątrz kontenera API.
- **Generowanie odpowiedzi (LLM):** Zewnętrzne API przez OpenRouter. Bardzo restrykcyjny System Prompt: _"Jesteś asystentem księgowym. Odpowiadaj na pytania WYŁĄCZNIE na podstawie dostarczonego kontekstu. Jeśli w kontekście nie ma odpowiedzi, napisz 'Brak informacji w dokumencie'."_

### 4. Strategia Chunkingu i Metadane

- **Chunking (Podział na sekcje logiczne):**
  - Aplikacja dzieli wyekstrahowany JSON na 3 sekcje logiczne: Nagłówek, Pozycje (Items), Podsumowanie.
  - _Token-aware:_ Przed wektoryzacją system sprawdza długość sekcji w tokenach/znakach. Jeśli sekcja (np. długa lista produktów) przekracza limit modelu (np. 400 tokenów), jest dzielona na mniejsze podsekcje.
  - _Formatowanie:_ JSON jest zamieniany na tekst Key-Value (np. "Sekcja: Nagłówek. Sprzedawca: X. Nabywca: Y.") dla lepszej jakości embeddingów.
- **Metadane w Qdrant (Payload):**
  - Każdy wektor musi zawierać w payloadzie: `document_id`, `section_type`, `source_text` (oryginalny tekst chunku), `invoice_no`, `date`, `buyer`, `seller`, `currency`, `total_net`, `total_vat`, `total_gross`.

### 5. Asynchroniczność i Obsługa Błędów

- Procesowanie VLM odbywa się w tle z użyciem `FastAPI BackgroundTasks`.
- Należy zaimplementować mechanizm ponowień (Retry) dla zapytań do OpenRouter (np. biblioteka `tenacity`, 3 próby).
- W przypadku ostatecznego błędu, status dokumentu w SQLite zmienia się na `failed`, a treść błędu jest zapisywana.

### 6. Specyfikacja Endpointów API

Aplikacja musi używać odpowiednich kodów HTTP (200, 202, 400, 404, 409, 422, 500).

1.  `GET /health` - Zwraca status aplikacji i połączenia z Qdrantem.
2.  `POST /documents/upload` - Przyjmuje plik (`.jpg`, `.jpeg`, `.png`). Zapisuje go na dysku, tworzy rekord w SQLite (status `queued`), uruchamia zadanie w tle i zwraca `document_id` (HTTP 202).
3.  `GET /documents/{document_id}` - Zwraca status (`queued`, `processing`, `completed`, `failed`), odczytany tekst, dane strukturalne lub błędy.
4.  `POST /documents/{document_id}/index` - Pobiera dane z SQLite, wykonuje chunking, tworzy embeddingi i zapisuje do Qdranta. Zwraca błąd 409, jeśli dokument nie ma statusu `completed`.
5.  `POST /rag/search` - Przyjmuje zapytanie tekstowe, zwraca najbardziej pasujące fragmenty (chunki) z Qdranta.
6.  `POST /rag/answer` - Przyjmuje zapytanie, wyszukuje kontekst w Qdrancie, buduje prompt dla LLM i zwraca odpowiedź wraz z użytymi źródłami (`document_id` i `source_text`).

### 7. Wymagania Kubernetes (Manifesty YAML)

Należy przygotować pliki YAML dla:

- **Namespace:** Np. `ai-rag-app`.
- **ConfigMap:** Konfiguracja aplikacji (np. `EMBEDDING_MODEL_NAME`, `QDRANT_HOST`, `QDRANT_PORT`, `LLM_MODEL_NAME`).
- **Secret:** Przechowywanie klucza `OPENROUTER_API_KEY`.
- **PersistentVolumeClaim (PVC):**
  - Jeden dla SQLite i plików tymczasowych (podpięty do API).
  - Drugi dla danych Qdranta (podpięty do bazy wektorowej).
- **Deployment (Qdrant):** Obraz `qdrant/qdrant:latest`. Limity zasobów: RAM (Requests: 256Mi, Limits: 512Mi), CPU (Limits: 500m).
- **Service (Qdrant):** Wystawienie portu 6333 wewnątrz klastra.
- **Deployment (FastAPI):** Obraz zbudowany z Dockerfile. Limity zasobów: RAM (Requests: 512Mi, Limits: 1024Mi), CPU (Limits: 1000m). Wstrzyknięcie zmiennych z ConfigMap i Secret.
- **Service (FastAPI):** Typ `NodePort`, aby umożliwić dostęp z poziomu przeglądarki/Postmana na localhost (Docker Desktop).

### 8. Dokumentacja (README.md)

Plik README musi zawierać:

1.  Instrukcję budowania obrazu Docker.
2.  Instrukcję uruchomienia aplikacji na lokalnym klastrze Kubernetes (komendy `kubectl apply`).
3.  Krótkie uzasadnienie architektoniczne: Dlaczego użyto `BackgroundTasks` zamiast Celery/Redis (wyjaśnienie trade-offu).
4.  **Odpowiedzi na pytania teoretyczne wymagane przez prowadzącego:**
    - Czym jest Dockerfile?
    - Czym jest `.dockerignore`?
    - Czym jest docker context?
    - Jak działają warstwy obrazu (image layers)?
    - Jak zoptymalizować czas budowy obrazu?
    - Dlaczego kolejność instrukcji w Dockerfile ma znaczenie?
