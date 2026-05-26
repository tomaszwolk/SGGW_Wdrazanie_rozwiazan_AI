# syntax=docker/dockerfile:1
# OCR/VLM RAG API — CPU-only PyTorch, pre-cached embedding model at build time.

FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock ./

# Dependencies only (app/ copied later for better layer cache).
RUN uv sync --frozen --no-install-project --no-dev

# torch is pinned to pytorch.org CPU index in pyproject.toml (no NVIDIA wheels in uv.lock).
# Fail the build if a CUDA-enabled PyTorch wheel was installed anyway.
RUN uv run python -c "\
import torch; \
cuda = torch.version.cuda; \
assert cuda is None, f'Expected CPU-only PyTorch, torch.version.cuda={cuda!r}'; \
assert not torch.cuda.is_available(); \
print('PyTorch', torch.__version__, '(CPU-only)')"

# Pre-cache Hugging Face / sentence-transformers weights (~80–120 MB for MiniLM).
ENV HF_HOME=/app/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/app/.cache/sentence_transformers \
    TRANSFORMERS_OFFLINE=0

ARG EMBEDDING_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2
RUN uv run python -c "\
from sentence_transformers import SentenceTransformer; \
name = '${EMBEDDING_MODEL_NAME}'; \
SentenceTransformer(name); \
print('Pre-cached embedding model:', name)"

COPY app ./app
RUN uv sync --frozen --no-dev


FROM python:3.12-slim-bookworm AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    HF_HOME=/app/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/app/.cache/sentence_transformers \
    NVIDIA_VISIBLE_DEVICES="" \
    CUDA_VISIBLE_DEVICES="" \
    SQLITE_PATH=/app/data/app.db \
    UPLOAD_DIR=/app/data/uploads

COPY --from=builder /app /app

RUN mkdir -p /app/data/uploads

EXPOSE 8000

# start-period: first boot loads FastAPI + may touch Qdrant in /health
HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
