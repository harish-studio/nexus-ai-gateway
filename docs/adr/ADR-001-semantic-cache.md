# ADR-001 — Semantic Cache: FastEmbed over sentence-transformers

**Date:** 2026-07-04   

---

## Context

`nexus-ai-gateway` requires a cache layer to avoid redundant LLM calls for
semantically similar questions. Two questions like "What is Python?" and
"Can you explain Python to me?" should return the same cached response,
not trigger two separate LLM calls at cost.

Two implementation options were evaluated:

| Option | Model size | Build time | Cold start | Quality |
|---|---|---|---|---|
| `sentence-transformers` (all-MiniLM-L6-v2) | ~90MB + PyTorch (~2GB) | ~20 min | ~4s | High |
| `fastembed` (BAAI/bge-small-en-v1.5) | ~73MB ONNX only | ~5 min | ~4s | Equivalent |

---

## Decision

**Use FastEmbed (`BAAI/bge-small-en-v1.5`) over sentence-transformers.**

Redis 8 vector search (native, no separate RediSearch module) stores
384-dimensional float32 vectors. Cosine similarity threshold: **0.92** —
empirically chosen to match paraphrases without false positives on
loosely related questions.

**Key reason:** `sentence-transformers` pulls PyTorch as a dependency
(~2GB). On a 4GB VRAM GTX 1650 already running Ollama inference,
adding PyTorch to the container image would cause memory pressure during
builds and inflate the image size unacceptably. FastEmbed uses ONNX
Runtime instead — same vector quality, ~97% smaller dependency footprint.

---

## Consequences

**Positive:**
- Docker image build time reduced from ~20 min to ~5 min
- No PyTorch dependency in the production image
- 51ms median latency on cache hits (measured under 5-user load test)
- Cache hit ratio tracked via `nexus_cache_hit_ratio` Prometheus gauge

**Negative:**
- FastEmbed's `FASTEMBED_CACHE_DIR` env var is ignored at import time in
  v0.8.0 — model must be pre-downloaded via `cache_dir=` constructor
  argument in the Dockerfile builder stage (documented workaround)

**Known gap:**
- High Risk (EU AI Act Annex III) requests bypass the cache entirely —
  they are re-evaluated fresh on every call for governance correctness

**Production upgrade path:**
- Switch from FLAT index (brute force) to HNSW index at >100k cached
  entries for O(log n) lookup instead of O(n)