# COST_MODEL.md — nexus-ai-gateway

## Overview

This document covers the per-request API token cost model for
`nexus-ai-gateway`. Infrastructure costs (Cloud Run, Cloud SQL,
Memorystore) will be added after the initial Cloud Run deployment
when real usage patterns are available.

> **Status:** Unit economics are based on verified provider pricing
> (June 2026). Volume projections marked `[TBD]` pending Cloud Run
> deployment.

---

## Provider pricing (verified June 2026)

All rates are USD per 1,000,000 tokens.
Source: provider pricing pages, cross-referenced June 2026.

| Provider | Model | Input ($/1M) | Output ($/1M) | Use case |
|---|---|---|---|---|
| Ollama | qwen3.5:4b | $0.00 | $0.00 | LOCAL preference, AUTO default |
| OpenAI | gpt-5.4-nano | $0.20 | $1.25 | FAST preference, ACCURATE downgrade |
| OpenAI | gpt-5.4 | $2.50 | $15.00 | FAST fallback, ACCURATE fallback |
| Anthropic | claude-sonnet-4-6 | $3.00 | $15.00 | ACCURATE preference |
| Anthropic | claude-haiku-4-5 | $1.00 | $5.00 | ACCURATE budget tier |
| Anthropic | claude-opus-4-8 | $5.00 | $25.00 | Highest capability |

> **Note on OpenAI pricing:** Multiple pricing tiers exist for GPT-5.x
> models as of June 2026. Verify current rates at
> `platform.openai.com/docs/pricing` before projecting costs —
> OpenAI has revised pricing several times in 2025–2026.

---

## Cost per request — unit economics

### Assumptions

- Average prompt: 50 input tokens (typical conversational query)
- Average response: 150 output tokens (concise gateway response,
  `max_tokens=200` default)
- Total: 200 tokens per request

### Cost per request by provider and model

| Provider | Model | Input cost | Output cost | Total per request |
|---|---|---|---|---|
| Ollama | qwen3.5:4b | $0.000000 | $0.000000 | **$0.000000** |
| OpenAI | gpt-5.4-nano | $0.000010 | $0.000188 | **$0.000198** |
| OpenAI | gpt-5.4 | $0.000125 | $0.002250 | **$0.002375** |
| Anthropic | claude-sonnet-4-6 | $0.000150 | $0.002250 | **$0.002400** |
| Anthropic | claude-opus-4-8 | $0.000250 | $0.003750 | **$0.004000** |

**Calculation:**
input_cost  = (input_tokens  / 1,000,000) × rate_per_1m_input
output_cost = (output_tokens / 1,000,000) × rate_per_1m_output
total       = input_cost + output_cost

Example — claude-sonnet-4-6, 50 input / 150 output tokens:
input_cost  = (50  / 1,000,000) × $3.00  = $0.000150
output_cost = (150 / 1,000,000) × $15.00 = $0.002250
total       = $0.002400 per request

---

## Cost optimisation mechanisms

### 1. Semantic cache (highest impact)

Every cache hit costs $0.00 in API tokens — the saved response is
served from Redis without any LLM call.

| Cache hit rate | Cost vs no cache | Saving |
|---|---|---|
| 0% (no cache) | Baseline | — |
| 30% hit rate | 70% of baseline | 30% saving |
| 50% hit rate | 50% of baseline | 50% saving |
| 70% hit rate | 30% of baseline | 70% saving |

Cache hit rate from Cloud Run deployment: **[TBD]**

**Cache cost:** FastEmbed embedding is computed locally (ONNX, no API
call). Redis vector search: negligible (~$0.001/hour for Cloud
Memorystore basic tier). Net cost of a cache hit: effectively $0.00.

### 2. Complexity-based routing (ACCURATE → cheaper on trivial prompts)

When `model_preference=accurate` is requested for a trivially simple
prompt (single message, under 20 words, no code/reasoning markers),
the gateway downgrades to `gpt-5.4-nano` instead of routing to
`claude-sonnet-4-6`.

| Scenario | Model used | Cost per request | Saving vs ACCURATE |
|---|---|---|---|
| Complex ACCURATE request | claude-sonnet-4-6 | $0.002400 | — |
| Trivial ACCURATE request (downgraded) | gpt-5.4-nano | $0.000198 | **91.75% saving** |

**Threshold:** prompts under 20 words with no code blocks or reasoning
keywords are classified as trivial. Configurable via `TRIVIAL_WORD_LIMIT`
constant in `app/services/complexity.py`.

### 3. Provider priority order (AUTO preference)

`AUTO` preference routes by priority: Ollama (1) → OpenAI (2) →
Anthropic (3). In local/development environments, Ollama handles
AUTO requests at $0.00 per token.

On Cloud Run (Ollama unavailable), AUTO falls through to OpenAI
(`gpt-5.4`) — the gateway's fallback chain handles this automatically.
Cloud Run AUTO request cost: **[TBD — depends on Ollama availability]**

### 4. Fallback chain cost implications

When a provider fails and the gateway falls back:

| Primary fails | Fallback to | Cost delta |
|---|---|---|
| Ollama → OpenAI (gpt-5.4) | +$0.002375 per request | |
| OpenAI → Anthropic (claude-sonnet-4-6) | +$0.000025 per request | |

Fallback rate from Cloud Run deployment: **[TBD]**

---

## Budget controls

Three independent budget protection layers:

### Layer 1 — Gateway rate limiting
- 10 requests/minute per API key
- 50 requests/hour per API key
- Prevents any single caller from exhausting credits

### Layer 2 — Provider-side spend caps
Set monthly hard limits directly in provider dashboards:
- OpenAI: `platform.openai.com` → Settings → Billing → Usage limits
- Anthropic: `console.anthropic.com` → Settings → Billing

**Recommended demo caps:**
- OpenAI: $10/month hard limit
- Anthropic: $10/month hard limit

Total maximum monthly API exposure: **$20** (before cache savings)

### Layer 3 — Semantic cache
Every cache hit is a zero-cost request. At 50% cache hit rate,
effective monthly spend is capped at **$10** (before infrastructure).

---

## Monthly cost projection (Cloud Run deployment)

| Traffic level | Requests/day | Cache hit rate | Est. monthly API cost |
|---|---|---|---|
| Low (demo only) | 50 | 40% | [TBD] |
| Medium (active recruiting) | 200 | 35% | [TBD] |
| High (live demo + testing) | 500 | 30% | [TBD] |

> _Update this table after Cloud Run deployment using actual
> `nexus_requests_total` and `nexus_cost_usd_total` Prometheus metrics._

---

## Cost tracking in production

Two Prometheus metrics track real-time spend:
nexus_cost_usd_total{provider="openai"}     # cumulative USD, OpenAI
nexus_cost_usd_total{provider="anthropic"}  # cumulative USD, Anthropic
nexus_cost_usd_total{provider="ollama"}     # always 0.0

Query total spend in the last 24 hours (PromQL):
increase(nexus_cost_usd_total[24h])

Query cost per provider as a percentage:
nexus_cost_usd_total / ignoring(provider) group_left
sum(nexus_cost_usd_total) * 100