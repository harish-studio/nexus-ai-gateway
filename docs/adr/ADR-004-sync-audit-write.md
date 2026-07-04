# ADR-004 — Audit Log: Synchronous Postgres Write over Redis Streams

**Date:** 2026-07-04  
**Status:** Accepted  
**Author:** [Your name]

---

## Context

Every gateway request must produce an immutable audit record capturing
routing decisions, governance outcomes, cost, and response integrity.
Three write strategies were evaluated:

| Strategy | Latency impact | Audit guarantee | Complexity |
|---|---|---|---|
| Synchronous Postgres write | +5–10ms per request | Strong — confirmed before response returned | Low |
| FastAPI `BackgroundTasks` | Zero | Weak — silent loss if DB unavailable | Low |
| Redis Streams + consumer | ~1ms to enqueue | Strong — queue persists if DB unavailable | High |

---

## Decision

**Use synchronous Postgres write before returning the response.**

The audit record is written and confirmed before the caller receives
their response. If the write fails, the failure is logged and the
response is still returned — the gateway degrades gracefully rather
than failing the entire request over an audit write error.

**Rationale over BackgroundTasks:** A governed enterprise gateway that
silently loses audit records when the DB is temporarily unavailable
cannot make a compliance guarantee. "We audit every request" requires
synchronous confirmation, not a fire-and-forget background task.

**Rationale over Redis Streams:** Redis Streams decouples write latency
from the request path (~1ms to enqueue vs ~10ms to write) and provides
durable queuing if Postgres is temporarily unavailable. However, it
requires a separate consumer process (startup, shutdown, error handling,
dead-letter queue) — meaningful additional infrastructure complexity
that is out of scope for this portfolio stage. The 5–10ms synchronous
write penalty is negligible at the current scale (sub-10 RPS).

---

## Audit record design

- **Immutable:** Pydantic `frozen=True` — record cannot be modified
  after creation, enforcing append-only semantics in application code
- **Integrity:** SHA-256 hash of full response content stored alongside
  a 200-character preview — full content is recoverable and verifiable
  without storing it in the audit log (GDPR data minimisation)
- **Idempotent:** `ON CONFLICT (request_id) DO NOTHING` — safe to retry
  without producing duplicate records
- **Indexed:** `timestamp DESC`, `user_id`, `risk_tier` — supports
  compliance queries ("all High Risk requests in the last 30 days")

---

## Consequences

**Positive:**
- Every request is guaranteed to be audited before the response
  is delivered — strong compliance posture
- `risk_tier`, `pii_entities`, `fallback_from`, `cache_hit`,
  `cost_usd` all captured per request — full governance audit trail
- `nexus_audit_writes_total{status="success|failed"}` Prometheus
  counter tracks write reliability in production

**Negative:**
- +5–10ms added to every request latency
- If Postgres is unavailable, audit records are lost for the
  duration of the outage (logged as warnings, not retried)

**Known gap:**
- Cache hit responses reuse the original LLM call's `latency_ms`
  value in the audit record — this overstates latency for cache
  hits (actual cache lookup is ~50ms, not the original 14s Ollama
  call). A future improvement would record actual cache lookup
  latency separately.

**Production upgrade path:**
- Replace synchronous write with Redis Streams consumer at
  throughput >1,000 requests/minute
- Add dead-letter queue for failed writes with automatic retry
- Consider Postgres partitioning by month for audit log tables
  exceeding 10M rows