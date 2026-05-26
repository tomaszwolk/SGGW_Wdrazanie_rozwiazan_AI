# Kubernetes manifests

| Plik | Zasób |
|------|--------|
| `01-namespace.yaml` | Namespace `ai-rag-app` |
| `02-storage.yaml` | PVC SQLite + Qdrant |
| `03-qdrant.yaml` | Qdrant Deployment + Service |
| `04-api.yaml` | API Deployment + LoadBalancer `:8000` |

**ConfigMap `app-config` i Secret `app-secrets`** nie są w repo — tworzy je [`../scripts/deploy-k8s.sh`](../scripts/deploy-k8s.sh) z pliku `.env`.

Wdrożenie: `./scripts/deploy-k8s.sh` — API na **http://localhost:8000** (jak lokalny dev).
