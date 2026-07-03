# Dockerfile

# ---- Stage 1: builder ----
FROM python:3.11-slim AS builder
WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Pre-download FastEmbed model via API-level cache_dir argument
RUN python -c "\
from fastembed import TextEmbedding; \
model = TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/root/.fastembed_cache'); \
list(model.embed(['warmup']))"

# Verify FastEmbed model landed correctly
RUN find /root/.fastembed_cache -name "*.onnx" | grep -q . || \
    (echo "ERROR: FastEmbed model not found" && exit 1)

# ---- Stage 2: runtime ----
FROM python:3.11-slim AS runtime

RUN useradd --create-home --shell /bin/bash appuser
WORKDIR /app

COPY --from=builder /root/.local /home/appuser/.local
COPY --from=builder /root/.fastembed_cache /home/appuser/.fastembed_cache

# Download spaCy model in runtime stage — registered in pip's package
# database so spacy.load('en_core_web_lg') works without path hacks
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

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]