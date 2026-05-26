#!/usr/bin/env bash
# Deploy OCR/VLM RAG API to local Kubernetes (Docker Desktop).
# Config: single .env (option B) — script builds ConfigMap + Secret and applies manifests.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

NAMESPACE="ai-rag-app"
HUB_IMAGE="tomaszwolk/ocr-rag-api:latest"
LOCAL_IMAGE="ocr-rag-api:latest"
API_URL="http://localhost:8000/health"

USE_LOCAL=false
DO_BUILD=false

usage() {
  cat <<'EOF'
Usage: ./scripts/deploy-k8s.sh [OPTIONS]

Deploy to namespace ai-rag-app using .env as the single configuration source.

Options:
  --local   Build ocr-rag-api:latest, import into the cluster node, use local image.
  --build   Implies --local; force docker build even if image exists.
  -h, --help

Default (no flags): pull/use tomaszwolk/ocr-rag-api:latest from Docker Hub (imagePullPolicy: IfNotPresent).

Requires: kubectl, docker, .env with OPENROUTER_API_KEY set.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --local) USE_LOCAL=true; shift ;;
    --build) USE_LOCAL=true; DO_BUILD=true; shift ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Error: '$1' not found in PATH." >&2
    exit 1
  fi
}

need_cmd kubectl
need_cmd docker

if [[ ! -f .env ]]; then
  echo "Error: .env not found. Copy .env.example to .env and set OPENROUTER_API_KEY." >&2
  exit 1
fi

# shellcheck source=/dev/null
set -a
source .env
set +a

if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
  echo "Error: OPENROUTER_API_KEY is empty in .env" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

CONFIG_ENV="$TMP_DIR/app-config.env"
SECRET_ENV="$TMP_DIR/app-secrets.env"

# ConfigMap: all keys from .env except the API key; K8s overrides below.
: >"$CONFIG_ENV"
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%$'\r'}"
  [[ "$line" =~ ^[[:space:]]*# ]] && continue
  [[ -z "${line//[[:space:]]}" ]] && continue
  key="${line%%=*}"
  key="${key#"${key%%[![:space:]]*}"}"
  key="${key%"${key##*[![:space:]]}"}"
  [[ "$key" == "OPENROUTER_API_KEY" ]] && continue
  val="${line#*=}"
  printf '%s=%s\n' "$key" "$val" >>"$CONFIG_ENV"
done <.env

# K8s-specific overrides (same .env for dev; cluster uses service names and PVC paths).
{
  grep -v -E '^(QDRANT_HOST|SQLITE_PATH|UPLOAD_DIR)=' "$CONFIG_ENV" || true
  echo "QDRANT_HOST=qdrant-service"
  echo "SQLITE_PATH=/app/data/app.db"
  echo "UPLOAD_DIR=/app/data/uploads"
} >"${CONFIG_ENV}.tmp"
mv "${CONFIG_ENV}.tmp" "$CONFIG_ENV"

printf 'OPENROUTER_API_KEY=%s\n' "$OPENROUTER_API_KEY" >"$SECRET_ENV"

echo "==> Namespace and storage"
kubectl apply -f k8s/01-namespace.yaml
kubectl apply -f k8s/02-storage.yaml

echo "==> ConfigMap and Secret from .env"
kubectl create configmap app-config \
  --from-env-file="$CONFIG_ENV" \
  -n "$NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic app-secrets \
  --from-env-file="$SECRET_ENV" \
  -n "$NAMESPACE" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> Qdrant"
kubectl apply -f k8s/03-qdrant.yaml

if [[ "$USE_LOCAL" == true ]]; then
  if [[ "$DO_BUILD" == true ]] || ! docker image inspect "$LOCAL_IMAGE" >/dev/null 2>&1; then
    echo "==> docker build -t $LOCAL_IMAGE ."
    docker build -t "$LOCAL_IMAGE" .
  else
    echo "==> Using existing local image $LOCAL_IMAGE (pass --build to rebuild)"
  fi
  K8S_NODE="$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}')"
  echo "==> Import $LOCAL_IMAGE into node $K8S_NODE (containerd)"
  if ! docker save "$LOCAL_IMAGE" | docker exec -i "$K8S_NODE" ctr -n k8s.io images import - 2>/dev/null; then
    echo "Warning: image import failed. Pod may still pull IfNotPresent if the image exists on the node." >&2
  fi
  TARGET_IMAGE="$LOCAL_IMAGE"
else
  TARGET_IMAGE="$HUB_IMAGE"
fi

echo "==> API (image: $TARGET_IMAGE)"
kubectl apply -f k8s/04-api.yaml
kubectl set image "deployment/api-deployment" "api=${TARGET_IMAGE}" -n "$NAMESPACE" --record=false

echo "==> Rollout restart (pick up ConfigMap / image)"
kubectl rollout restart deployment/api-deployment -n "$NAMESPACE"

echo "==> Waiting for Qdrant..."
kubectl rollout status deployment/qdrant-deployment -n "$NAMESPACE" --timeout=120s

echo "==> Waiting for API (embedder startup may take 2–4 min)..."
kubectl rollout status deployment/api-deployment -n "$NAMESPACE" --timeout=360s

echo ""
echo "Deployed. API: http://localhost:8000/docs"
echo "Health:  $API_URL"
if command -v curl >/dev/null 2>&1; then
  code="$(curl -s -o /dev/null -w '%{http_code}' "$API_URL" || true)"
  echo "Health check HTTP: ${code:-failed}"
fi
