# db-plan.md

## Architektura Baz Danych

Projekt wykorzystuje architekturę hybrydową (Dual-Database), rozdzielając zarządzanie stanem aplikacji od wyszukiwania semantycznego:

1. **SQLite** – relacyjna baza danych pełniąca rolę "Source of Truth" dla stanu przetwarzania dokumentów oraz przechowująca surowe wyniki z modelu VLM.
2. **Qdrant** – baza wektorowa zoptymalizowana pod kątem wyszukiwania semantycznego (RAG) oraz filtrowania po metadanych (Hybrid Search).

---

## 1. Relacyjna Baza Danych: SQLite

### Cel

Przechowywanie metadanych o przesłanych plikach, śledzenie asynchronicznego statusu przetwarzania (VLM) oraz archiwizacja wyekstrahowanych danych strukturalnych.

### Technologia i Wdrożenie

- **Silnik:** SQLite3.
- **ORM:** SQLAlchemy lub SQLModel (zintegrowany z Pydantic).
- **Storage (Kubernetes):** Plik bazy (np. `app.db`) musi być zapisywany na wolumenie trwałym (Persistent Volume Claim) podmontowanym do kontenera FastAPI (np. w ścieżce `/app/data/`), aby dane przetrwały restart Poda.

### Schemat: Tabela `documents`

| Kolumna           | Typ Danych    | Ograniczenia                | Opis                                                                 |
| :---------------- | :------------ | :-------------------------- | :------------------------------------------------------------------- |
| `id`              | String (UUID) | Primary Key                 | Unikalny identyfikator dokumentu.                                    |
| `filename`        | String        | Not Null                    | Oryginalna nazwa przesłanego pliku.                                  |
| `status`          | Enum / String | Not Null, Default: `queued` | Status przetwarzania: `queued`, `processing`, `completed`, `failed`. |
| `raw_text`        | Text          | Nullable                    | Pełny, surowy tekst odczytany przez VLM.                             |
| `structured_data` | JSON / Text   | Nullable                    | Odpowiedź z VLM w formacie JSON (zawiera wyekstrahowane pola).       |
| `error_message`   | Text          | Nullable                    | Treść błędu, jeśli status to `failed`.                               |
| `created_at`      | DateTime      | Not Null, Default: `now()`  | Data i czas utworzenia rekordu.                                      |
| `updated_at`      | DateTime      | Not Null, Default: `now()`  | Data i czas ostatniej aktualizacji statusu.                          |

_Uwaga techniczna: Ponieważ SQLite nie posiada natywnego typu JSON, kolumna `structured_data` będzie fizycznie przechowywana jako tekst (TEXT), a parsowana do słownika/Pydantic na poziomie ORM._

---

## 2. Baza Wektorowa: Qdrant

### Cel

Przechowywanie wektorów (embeddingów) wygenerowanych z fragmentów tekstu (chunków) oraz bogatych metadanych umożliwiających wyszukiwanie hybrydowe (tekstowe + filtrowanie po wartościach liczbowych).

### Technologia i Wdrożenie

- **Silnik:** Qdrant (wersja serwerowa, obraz Docker: `qdrant/qdrant:latest`).
- **Klient:** Oficjalna biblioteka `qdrant-client` w Pythonie.
- **Storage (Kubernetes):** Osobny Deployment w K8s z własnym Persistent Volume Claim podmontowanym w ścieżce `/qdrant/storage`.

### Konfiguracja Kolekcji (Collection)

- **Nazwa kolekcji:** `documents_index` (lub ładowana ze zmiennych środowiskowych).
- **Rozmiar wektora (Dimension):** `384` (wymóg dla modelu `sentence-transformers/all-MiniLM-L6-v2`).
- **Metryka dystansu:** `Cosine` (Kosinusowa).

### Schemat Metadanych (Qdrant Payload)

Każdy wektor (Point) w Qdrancie reprezentuje jeden chunk logiczny dokumentu (np. nagłówek, podsumowanie). Oprócz samego wektora, do punktu dołączony jest Payload (JSON) o następującej strukturze:

| Klucz (Pole)   | Typ Danych    | Opis / Przykład                                                                                     | Wymagane |
| :------------- | :------------ | :-------------------------------------------------------------------------------------------------- | :------- |
| `document_id`  | String (UUID) | Klucz obcy łączący wektor z rekordem w SQLite.                                                      | Tak      |
| `section_type` | String        | Typ chunku: `header`, `items`, `summary`.                                                           | Tak      |
| `source_text`  | String        | Złożony tekst (Key-Value), który posłużył do wygenerowania wektora. Zwracany do LLMa jako kontekst. | Tak      |
| `filename`     | String        | Nazwa pliku źródłowego.                                                                             | Tak      |
| `date`         | String        | Data wystawienia dokumentu (np. "2023-10-12").                                                      | Nie      |
| `buyer`        | String        | Nazwa nabywcy.                                                                                      | Nie      |
| `seller`       | String        | Nazwa sprzedawcy.                                                                                   | Nie      |
| `currency`     | String        | Waluta (np. "PLN", "EUR").                                                                          | Nie      |
| `total_net`    | Float         | Kwota netto.                                                                                        | Nie      |
| `total_vat`    | Float         | Kwota podatku VAT.                                                                                  | Nie      |
| `total_gross`  | Float         | Kwota brutto (suma końcowa).                                                                        | Nie      |

### Indeksowanie Payloadu (Opcjonalne, zalecane)

Aby zoptymalizować wyszukiwanie dla trudnych pytań analitycznych (np. "Który dokument ma najwyższą kwotę?"), w Qdrancie należy założyć indeksy na pola numeryczne w Payloadzie:

- Indeks typu `Float` na pole `total_gross`.

---

## 3. Przepływ Danych (Data Flow)

1. **Upload (`POST /documents/upload`):** Tworzony jest nowy rekord w SQLite ze statusem `queued`. Zwracany jest `id`.
2. **Background Task (VLM):** Pobiera plik, wysyła do VLM. Wynik (JSON) jest zapisywany w SQLite w kolumnie `structured_data`, a status zmienia się na `completed`.
3. **Indeksowanie (`POST /documents/{id}/index`):**
   - Aplikacja pobiera `structured_data` z SQLite.
   - Dzieli dane na sekcje logiczne (chunking).
   - Generuje embeddingi dla każdej sekcji.
   - Zapisuje wektory wraz z Payloadem do Qdranta.
4. **Wyszukiwanie (`POST /rag/search` i `POST /rag/answer`):**
   - Zapytanie użytkownika jest zamieniane na wektor.
   - Qdrant zwraca najbardziej podobne wektory wraz z ich Payloadem (`source_text` i metadane).
   - (Tylko `answer`) Pobrany `source_text` trafia jako kontekst do promptu dla LLM.
