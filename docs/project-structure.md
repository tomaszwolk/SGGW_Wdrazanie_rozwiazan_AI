ocr-rag-api/
├── app/ # Główny katalog aplikacji (kod źródłowy Python)
│ ├── **init**.py
│ ├── main.py # Inicjalizacja FastAPI, podpięcie routerów i obsługa błędów
│ ├── core/
│ │ ├── **init**.py
│ │ └── config.py # Konfiguracja aplikacji (pydantic-settings, ładowanie env)
│ ├── api/
│ │ ├── **init**.py
│ │ ├── health.py # Endpoint: /health
│ │ ├── documents.py # Endpointy: /documents/upload, /documents/{id}, /documents/{id}/index
│ │ └── rag.py # Endpointy: /rag/search, /rag/answer
│ ├── models/
│ │ ├── **init**.py
│ │ ├── domain.py # Modele bazy danych (SQLite - np. SQLAlchemy lub SQLModel)
│ │ └── schemas.py # Modele Pydantic (walidacja Request/Response dla API)
│ ├── services/
│ │ ├── **init**.py
│ │ ├── vlm_service.py # Logika komunikacji z OpenRouter (ekstrakcja JSON z obrazu)
│ │ ├── rag_service.py # Logika RAG: embeddingi, wyszukiwanie w Qdrant, generowanie odpowiedzi
│ │ └── background_tasks.py # Funkcje uruchamiane w tle (obsługa statusów, retry)
│ ├── db/
│ │ ├── **init**.py
│ │ ├── sqlite.py # Konfiguracja połączenia i sesji SQLite
│ │ └── qdrant.py # Konfiguracja i inicjalizacja klienta Qdrant
│ └── utils/
│ ├── **init**.py
│ ├── upload_validation.py # Walidacja przesłanych plików
│ └── text_processing.py # Funkcje pomocnicze: chunking, liczenie tokenów, formatowanie Key-Value
│
├── k8s/ # Manifesty Kubernetes
│ ├── 01-namespace.yaml
│ ├── 02-config.yaml
│ ├── 03-storage.yaml
│ ├── 04-qdrant.yaml
│ └── 05-api.yaml
│
├── docs/ # Pliki planistyczne
│ ├── prd.md
│ ├── db-plan.md
│ ├── Faktury - Zadanie zaliczeniowe.docx # Wymagania prowadzącego
│ ├── api-plan.md
│ └── k8s-plan.md
│
├── data/ # Katalog na pliki tymczasowe i bazę SQLite (montowany jako PVC w K8s)
│ └── .gitkeep # Pusty plik, by Git śledził ten folder
│
├── .env.example # Przykładowy plik ze zmiennymi środowiskowymi
├── .gitignore
├── .dockerignore
├── .python-version
├── Dockerfile
├── pyproject.toml
├── README.md
└── uv.lock
