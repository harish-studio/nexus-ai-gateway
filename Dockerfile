# Dockerfile

# ---- Stage 1: builder ----
FROM python:3.11.9-slim AS builder
WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Pin pip to avoid self-upgrade warnings and ensure reproducible resolution
RUN pip install --no-cache-dir --upgrade pip==24.0

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Pre-download FastEmbed model via API-level cache_dir argument —
# env var approach is unreliable in fastembed 0.8.0
RUN python -c "\
from fastembed import TextEmbedding; \
model = TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/root/.fastembed_cache'); \
list(model.embed(['warmup']))"

# Build-time assertion — fails loudly if model didn't land correctly
RUN find /root/.fastembed_cache -name "*.onnx" | grep -q . || \
    (echo "ERROR: FastEmbed model not found at /root/.fastembed_cache" && exit 1)

# ---- Stage 2: runtime ----
FROM python:3.11.9-slim AS runtime

# Install curl for HEALTHCHECK — kept minimal, no other additions
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash appuser
WORKDIR /app

COPY --from=builder /root/.local /home/appuser/.local
COPY --from=builder /root/.fastembed_cache /home/appuser/.fastembed_cache

# Download spaCy model in runtime stage as root — registers in pip's
# package database so spacy.load('en_core_web_lg') resolves correctly.
# Runs as root intentionally (before USER appuser) so pip writes to
# system site-packages; read access by appuser is sufficient at runtime.
# Known gap: production Dockerfile.prod would install as appuser instead.
RUN pip install --no-cache-dir --no-deps \
    https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.8.0/en_core_web_lg-3.8.0-py3-none-any.whl

COPY app/ ./app/
COPY config/ ./config/
COPY tests/ ./tests/

ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV FASTEMBED_CACHE_DIR=/home/appuser/.fastembed_cache

RUN chown -R appuser:appuser /app /home/appuser/.local /home/appuser/.fastembed_cache
USER appuser

# Expose API port and Prometheus metrics port
EXPOSE 8000
EXPOSE 9090

# Health check — queries the /health endpoint every 30s.
# 3 retries × 10s timeout = 30s grace period before Docker marks unhealthy.
# start_period=60s accounts for spaCy/FastEmbed cold-start on first request.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=60s \
    CMD curl -f -H "X-API-Key: ${HEALTHCHECK_API_KEY}" \
        http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]