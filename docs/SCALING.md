# SCALING.md — nexus-ai-gateway

## Overview

This document describes the gateway's scaling characteristics, known
bottlenecks, and production architecture recommendations.

Performance baseline numbers are captured from the Cloud Run deployment
and will be updated here after the initial deployment run.

> **Baseline status:** _Pending Cloud Run deployment — placeholders
> marked with `[TBD]` throughout this document._

---

## Current architecture (local / development)
┌─────────────────────────────────────────────────────┐
│                   Docker Compose                     │
│                                                      │
│  nexus-ai-gateway (FastAPI, 2 uvicorn workers)       │
│  Redis 8 (vector index + rate limit counters)        │
│  Postgres 16 (audit log)                             │
│                                                      │
│  Ollama (Windows host, GTX 1650 4GB VRAM)            │
│  OpenAI / Anthropic (external API)                   │
└─────────────────────────────────────────────────────┘

**Local constraints (not representative of production):**
- Single GTX 1650 serialises Ollama inference — one request at a time
- One API key shared across load test users triggers rate limiting early
- Docker-on-Windows adds ~10–20ms overhead vs native Linux

---

## Bottleneck analysis

### Observed bottleneck order (local load test, 5 concurrent users)

1. **Rate limiter** — 10 requests/minute per API key. At 5 concurrent
   users sharing one key, ceiling is hit within 60 seconds.
   _Production mitigation:_ issue separate keys per user; each key has
   its own independent counter.

2. **Ollama GPU serialisation** — GTX 1650 handles one inference at a
   time. Novel queries queue behind each other.
   _Production mitigation:_ Cloud Run routes novel queries to
   OpenAI/Anthropic (parallel, elastic); Ollama is dev-only.

3. **Connection exhaustion** — 2 occurrences of `ConnectionResetError`
   under concurrent load.
   _Production mitigation:_ Cloud Run autoscales container instances;
   connection pool is shared across requests, not per-request.

### Local baseline (Docker, GTX 1650, 5 users, 60s run)

| Metric | Value | Notes |
|---|---|---|
| Aggregate RPS | [TBD — pending Cloud Run] | Local: 0.65 RPS (rate-limit constrained) |
| Cache hit median latency | [TBD] | Local: 51ms |
| Novel query p95 latency | [TBD] | Local: dominated by Ollama GPU queue |
| Failure rate | [TBD] | Local: 51% (rate limiting, not app errors) |

---

## Cloud Run architecture

### Target configuration

| Parameter | Value | Rationale |
|---|---|---|
| Instance size | 2 vCPU, 2GB RAM | Handles moderate concurrency; Cloud Run default |
| Min instances | 0 | Scale to zero when idle — cost protection |
| Max instances | 3 | Caps concurrent LLM API spend |
| Concurrency | 10 per instance | FastAPI async; IO-bound workload |
| Region | europe-west4 (Netherlands) | EU data residency alignment |

### Managed services

| Service | Local equivalent | Cloud Run equivalent |
|---|---|---|
| Redis | Redis 8 (Docker) | Cloud Memorystore for Redis |
| Postgres | Postgres 16 (Docker) | Cloud SQL for Postgres |
| Secrets | `.env` file | Google Secret Manager |
| Ingress protection | slowapi rate limiter | Cloud Armor WAF + slowapi |

### Cloud Run baseline (pending deployment)

| Metric | Value |
|---|---|
| Cold start latency | [TBD] |
| Warm request p50 | [TBD] |
| Warm request p95 | [TBD] |
| Cache hit p50 | [TBD] |
| Cache hit p95 | [TBD] |
| Max sustainable RPS (3 instances) | [TBD] |
| First bottleneck under load | [TBD] |

> _Table to be updated after running:_
> ```bash
> locust -f tests/load/locustfile.py \
>   --host https://[CLOUD-RUN-URL] \
>   --headless -u 20 -r 2 -t 120s
> ```

---

## Scaling strategy

### What scales automatically

- **Cloud Run instances** — autoscale 0→3 on incoming requests
- **Redis vector index** — FLAT index handles up to ~100k cached entries
  at acceptable latency; switch to HNSW at >100k entries
- **Postgres** — Cloud SQL scales vertically; connection pooling via
  `asyncpg` handles burst connections

### What requires manual intervention

- **Rate limits** — `10/min · 50/hour` per key is hardcoded in
  `app/services/limiter.py`. Adjust via `RATE_LIMIT_PER_MINUTE` and
  `RATE_LIMIT_PER_HOUR` environment variables (to be added).
- **Semantic cache threshold** — 0.92 cosine similarity is a constant
  in `app/services/semantic_cache.py`. Lower threshold = more cache hits
  but higher false-match risk.
- **Fallback chain** — provider priority order (Ollama → OpenAI →
  Anthropic) is hardcoded in `app/services/fallback.py`. On Cloud Run,
  Ollama is unavailable — the chain effectively becomes OpenAI → Anthropic.

### Known scaling gaps

1. **Ollama unavailable on Cloud Run** — `LOCAL` model preference will
   fallback to OpenAI (priority 2) per the fallback chain design.
   Document this clearly in the API contract for Cloud Run deployments.

2. **Audit write is synchronous** — at >1,000 requests/minute, the
   +5–10ms Postgres write becomes a meaningful latency contributor.
   Upgrade path: Redis Streams consumer (see ADR-004).

3. **Single Redis instance** — no Redis Cluster or Sentinel. Acceptable
   for portfolio scale; production would use Cloud Memorystore with
   high-availability replica.

4. **Streaming PII check not implemented** — `/chat/stream` does not
   scan responses for PII. Mitigation: request-side PII check is still
   enforced; response scanning requires buffering the full stream before
   yielding (deferred to production hardening).

5. **spaCy cold start** — first request after container start triggers
   Presidio's spaCy model loading (~2–4s). `HEALTHCHECK` start_period of
   60s accounts for this in Docker; Cloud Run's startup probe should
   be configured similarly.

---

## Cost scaling

See [COST_MODEL.md](COST_MODEL.md) for per-request cost breakdown and
cache savings analysis.

**Key cost levers:**
1. Cache hit rate — every cache hit saves the full LLM API cost
2. Complexity routing — trivial ACCURATE requests downgraded to
   `gpt-5.4-nano` ($0.20/1M input vs $3.00/1M for Sonnet 4.6)
3. LOCAL preference — Ollama inference costs $0.00 per token
4. Provider priority — Ollama (free) tried before OpenAI before Anthropic