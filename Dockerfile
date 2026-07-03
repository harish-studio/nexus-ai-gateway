# Dockerfile

# ---- Stage 1: builder ----
FROM python:3.11-slim AS builder
WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Download spaCy model into user packages during build
RUN python -m spacy download en_core_web_lg

# ---- Stage 2: runtime ----
FROM python:3.11-slim AS runtime

RUN useradd --create-home --shell /bin/bash appuser
WORKDIR /app

# Copy installed packages AND spaCy model from builder
COPY --from=builder /root/.local /home/appuser/.local

# Copy application code and tests
COPY app/ ./app/
COPY config/ ./config/
COPY tests/ ./tests/

ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Fix ownership so appuser can read the spaCy model
RUN chown -R appuser:appuser /app /home/appuser/.local

USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]