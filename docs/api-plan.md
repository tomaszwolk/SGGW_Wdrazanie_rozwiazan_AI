# api-plan.md

## Specyfikacja API (REST)

Dokument opisuje kontrakty dla wszystkich endpointów aplikacji OCR/VLM RAG API.
Wszystkie endpointy zwracają dane w formacie JSON (z wyjątkiem błędów walidacji FastAPI, które mają swój standardowy format).

---

### 1. Sprawdzenie statusu aplikacji

- **Endpoint:** `GET /health`
- **Opis:** Służy do monitorowania stanu aplikacji (Health Check). Sprawdza, czy API działa oraz czy jest aktywne połączenie z bazą SQLite i Qdrant.
- **Autentykacja:** Brak
- **Parametry ścieżki:** Brak
- **Request Body:** Brak
- **Success Response (200 OK):**
  ```json
  {
    "status": "ok",
    "sqlite_connection": "ok",
    "qdrant_connection": "ok"
  }
  ```
- **Error Responses:**
  - `500 Internal Server Error` – Aplikacja działa, ale wystąpił błąd połączenia z którąś z baz danych.

---

### 2. Wgranie dokumentu

- **Endpoint:** `POST /documents/upload`
- **Opis:** Przyjmuje plik obrazu (faktura/paragon), zapisuje go tymczasowo na dysku, tworzy rekord w bazie SQLite ze statusem `queued` i uruchamia asynchroniczne zadanie ekstrakcji danych (VLM).
- **Autentykacja:** Brak
- **Content-Type:** `multipart/form-data`
- **Request Body:**
  - Pole formularza: `file` (typ: plik binarny, dozwolone rozszerzenia: `.jpg`, `.jpeg`, `.png`)
- **Success Response (202 Accepted):**
  ```json
  {
    "document_id": "123e4567-e89b-12d3-a456-426614174000",
    "status": "queued",
    "message": "Dokument został przyjęty do przetwarzania."
  }
  ```
- **Error Responses:**
  - `400 Bad Request` – Nieobsługiwany format pliku (np. `.pdf` lub `.txt`).
  - `422 Unprocessable Entity` – Brak pliku w żądaniu.

---

### 3. Pobranie statusu i danych dokumentu

- **Endpoint:** `GET /documents/{document_id}`
- **Opis:** Zwraca aktualny status przetwarzania dokumentu. Jeśli przetwarzanie zakończyło się sukcesem, zwraca również wyekstrahowany tekst i dane strukturalne.
- **Autentykacja:** Brak
- **Parametry ścieżki:** `document_id` (UUID)
- **Request Body:** Brak
- **Success Response (200 OK):**
  ```json
  {
    "document_id": "123e4567-e89b-12d3-a456-426614174000",
    "status": "completed",
    "raw_text": "Pełny tekst odczytany z dokumentu...",
    "structured_data": {
      "filename": "faktura_123.jpg",
      "date": "2023-10-12",
      "buyer": "Firma ABC",
      "seller": "Sklep XYZ",
      "total_gross": 150.50,
      "items": [...]
    },
    "error_message": null
  }
  ```
  _(Uwaga: pola `raw_text` i `structured_data` mogą być `null`, jeśli status to `queued`, `processing` lub `failed`)_
- **Error Responses:**
  - `404 Not Found` – Brak dokumentu o podanym ID w bazie SQLite.
  - `422 Unprocessable Entity` – Podany `document_id` nie jest poprawnym formatem UUID.

---

### 4. Indeksowanie dokumentu (RAG)

- **Endpoint:** `POST /documents/{document_id}/index`
- **Opis:** Pobiera przetworzone dane dokumentu z bazy SQLite, wykonuje podział na sekcje (chunking), generuje embeddingi i zapisuje je wraz z metadanymi do bazy wektorowej Qdrant.
- **Autentykacja:** Brak
- **Parametry ścieżki:** `document_id` (UUID)
- **Request Body:** Brak
- **Success Response (200 OK):**
  ```json
  {
    "document_id": "123e4567-e89b-12d3-a456-426614174000",
    "message": "Dokument został pomyślnie zaindeksowany.",
    "chunks_indexed": 3
  }
  ```
- **Error Responses:**
  - `404 Not Found` – Brak dokumentu o podanym ID.
  - `409 Conflict` – Dokument nie ma statusu `completed` (np. wciąż się przetwarza lub wystąpił błąd VLM), więc nie można go zaindeksować.
  - `500 Internal Server Error` – Błąd podczas generowania embeddingów lub komunikacji z Qdrantem.

---

### 5. Wyszukiwanie semantyczne (Search)

- **Endpoint:** `POST /rag/search`
- **Opis:** Wyszukuje w bazie Qdrant fragmenty dokumentów najbardziej odpowiadające zapytaniu użytkownika pod względem znaczenia (podobieństwo kosinusowe).
- **Autentykacja:** Brak
- **Content-Type:** `application/json`
- **Request Body:**
  ```json
  {
    "query": "Kto kupił mleko?",
    "top_k": 5
  }
  ```
  _(Pole `top_k` jest opcjonalne, domyślnie np. 3)_
- **Success Response (200 OK):**
  ```json
  {
    "query": "Kto kupił mleko?",
    "results": [
      {
        "document_id": "123e...",
        "score": 0.89,
        "section_type": "items",
        "source_text": "Sekcja: Pozycje. Produkt: Mleko 2%. Cena: 3.50 PLN.",
        "metadata": {
          "filename": "paragon_1.jpg",
          "date": "2023-10-12"
        }
      }
    ]
  }
  ```
- **Error Responses:**
  - `422 Unprocessable Entity` – Brak pola `query` w ciele żądania.
  - `500 Internal Server Error` – Błąd komunikacji z Qdrantem.

---

### 6. Odpowiedź RAG (Answer)

- **Endpoint:** `POST /rag/answer`
- **Opis:** Realizuje pełny proces RAG. Wyszukuje kontekst w Qdrancie (podobnie jak `/search`), buduje prompt, wysyła go do modelu LLM (OpenRouter) i zwraca wygenerowaną odpowiedź opartą wyłącznie na znalezionych dokumentach.
- **Autentykacja:** Brak
- **Content-Type:** `application/json`
- **Request Body:**
  ```json
  {
    "question": "Jaka jest najwyższa kwota na fakturach z października?"
  }
  ```
- **Success Response (200 OK):**
  ```json
  {
    "question": "Jaka jest najwyższa kwota na fakturach z października?",
    "answer": "Najwyższa kwota na fakturach z października to 150.50 PLN (Firma ABC).",
    "sources": [
      {
        "document_id": "123e...",
        "source_text": "Sekcja: Podsumowanie. Kwota brutto: 150.50 PLN."
      }
    ]
  }
  ```
- **Error Responses:**
  - `422 Unprocessable Entity` – Brak pola `question` w ciele żądania.
  - `500 Internal Server Error` – Błąd zewnętrznego API (OpenRouter) lub błąd bazy Qdrant.
