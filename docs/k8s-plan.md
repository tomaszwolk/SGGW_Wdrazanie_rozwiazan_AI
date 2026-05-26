# k8s-plan.md

## Architektura Kubernetes (Docker Desktop)

Dokument opisuje strukturę manifestów YAML niezbędnych do wdrożenia aplikacji OCR/VLM RAG API na lokalnym klastrze Kubernetes. Architektura opiera się na dwóch głównych mikroserwisach: API (FastAPI) oraz Bazie Wektorowej (Qdrant).

Wszystkie zasoby zostaną wdrożone w dedykowanej przestrzeni nazw (Namespace), aby odizolować projekt od reszty klastra.

---

## 1. Przestrzeń nazw (Namespace)

- **Plik:** `01-namespace.yaml`
- **Zasób:** `Namespace`
- **Nazwa:** `ai-rag-app`
- **Cel:** Logiczna izolacja wszystkich komponentów aplikacji. Wszystkie kolejne zasoby będą wdrażane w tym Namespace.

---

## 2. Konfiguracja i Sekrety (Config & Secrets)

- **ConfigMap / Secret:** generowane przez `scripts/deploy-k8s.sh` z `.env` (ConfigMap + nadpisania K8s; Secret tylko `OPENROUTER_API_KEY`). Patrz [k8s/README.md](../k8s/README.md).

---

## 3. Pamięć Trwała (Storage)

Ponieważ kontenery są ulotne (stateless), potrzebujemy wolumenów, aby nie stracić bazy SQLite, wgranych plików i wektorów po restarcie Poda. W Docker Desktop domyślna klasa pamięci (StorageClass) automatycznie przydzieli miejsce na dysku hosta.

- **Plik:** `02-storage.yaml`
- **Zasób 1:** `PersistentVolumeClaim` (Nazwa: `sqlite-data-pvc`)
  - **Pojemność:** `1Gi`
  - **Tryb dostępu:** `ReadWriteOnce`
  - **Cel:** Przechowywanie pliku `app.db` oraz tymczasowych obrazów w kontenerze FastAPI.
- **Zasób 2:** `PersistentVolumeClaim` (Nazwa: `qdrant-data-pvc`)
  - **Pojemność:** `2Gi`
  - **Tryb dostępu:** `ReadWriteOnce`
  - **Cel:** Przechowywanie kolekcji i wektorów bazy Qdrant.

---

## 4. Baza Wektorowa (Qdrant)

- **Plik:** `03-qdrant.yaml`
- **Zasób 1:** `Deployment` (Nazwa: `qdrant-deployment`)
  - **Obraz:** `qdrant/qdrant:latest`
  - **Replik:** 1
  - **Zarządzanie zasobami (Kluczowe dla słabych PC!):**
    - Requests: `CPU: 200m`, `Memory: 256Mi`
    - Limits: `CPU: 500m`, `Memory: 512Mi`
  - **Volume Mounts:** Podmontowanie `qdrant-data-pvc` do ścieżki `/qdrant/storage`.
- **Zasób 2:** `Service` (Nazwa: `qdrant-service`)
  - **Typ:** `ClusterIP` (Dostępny TYLKO wewnątrz klastra, nie wystawiamy bazy na zewnątrz).
  - **Porty:** `6333` (HTTP) mapowany na port `6333` kontenera.

---

## 5. Aplikacja API (FastAPI)

- **Plik:** `04-api.yaml`
- **Zasób 1:** `Deployment` (Nazwa: `api-deployment`)
  - **Obraz:** `ocr-rag-api:latest` (Obraz zbudowany lokalnie z Dockerfile, polityka `imagePullPolicy: Never` lub `IfNotPresent`).
  - **Replik:** 1
  - **Zmienne środowiskowe (Env):** Wstrzykiwane z `ConfigMap` (`app-config`) oraz `Secret` (`app-secrets`).
  - **Zarządzanie zasobami (Kluczowe dla słabych PC!):**
    - Requests: `CPU: 300m`, `Memory: 512Mi`
    - Limits: `CPU: 1000m`, `Memory: 1024Mi` (Wymagane do załadowania modelu embeddingów do RAM).
  - **Volume Mounts:** Podmontowanie `sqlite-data-pvc` do ścieżki `/app/data`.
  - **Probes (Health Checks):**
    - `livenessProbe`: HTTP GET na `/health` (Port 8000). Sprawdza, czy aplikacja nie zawiesiła się.
    - `readinessProbe`: HTTP GET na `/health` (Port 8000). Sprawdza, czy aplikacja jest gotowa przyjmować ruch.
- **Zasób 2:** `Service` (Nazwa: `api-service`)
  - **Typ:** `LoadBalancer` (Docker Desktop mapuje `localhost:8000` — ten sam port co lokalny dev).
  - **Porty:** Port serwisu `8000` → `targetPort` `8000`.

---

## 6. Kolejność Wdrażania (Deployment Order)

W pliku `README.md` znajdzie się instrukcja, aby aplikować manifesty w następującej kolejności (lub użyć jednego połączonego pliku `k8s-all.yaml`):

1. `./scripts/deploy-k8s.sh` (zalecane), albo ręcznie: `01` → ConfigMap/Secret ze skryptu → `02`–`04`.
