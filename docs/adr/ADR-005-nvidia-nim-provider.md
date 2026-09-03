# ADR-005 — NVIDIA Nemotron: Dual-Path Provider (Hosted NIM + Local Ollama)

**Date:** 2026-09-03

---

## Context

The gateway routes requests across multiple LLM providers via a
LiteLLM abstraction layer. Adding NVIDIA Nemotron to the provider
registry required a choice between three deployment modes:

| Strategy | GPU requirement | Latency floor | Data residency | Cost |
|---|---|---|---|---|
| Hosted NIM endpoint (NVIDIA Developer Programme) | None | ~1,000ms (network RTT) | NVIDIA US infrastructure | Zero — free tier |
| Self-hosted NIM container | NVIDIA GPU instance required | ~50–200ms (local inference) | Operator-controlled | GPU instance cost + ops |
| Local weights via Ollama | None (CPU-only viable for small variants) | ~500–2,000ms (CPU inference) | Fully local | Zero |

The gateway already runs four governance layers before an LLM call
reaches the provider: EU AI Act risk classification, PII detection and
redaction, semantic cache lookup, and rate limiting. These layers apply
for all the providers.

A single deployment mode cannot satisfy all use cases simultaneously:
the hosted endpoint shows integration with NVIDIA's production
platform but offers no data residency guarantee. Local weights via
Ollama guarantee data residency but are limited to smaller models on CPU-only hardware.

---

## Decision

**Implement both paths as separate `ModelPreference` values:**

- `ModelPreference.NVIDIA` — routes to hosted NIM endpoint
  (`nvidia/nemotron-3.5-lightning-30b-a3b` via
  `https://integrate.api.nvidia.com/v1`). This shows integration
  with NVIDIA's production platform. It is appropriate to use for workloads where
  completion content does not have personal data.

- `ModelPreference.NVIDIA_LOCAL` — routes to Nemotron-mini pulled
  locally via Ollama for strict data localisation requirements. 
  The gateway's PII gate prevents personal data reaching
  any external provider by design. NVIDIA_LOCAL provides an additional
  control layer for workloads requiring hard localisation regardless
  of PII content.

Both paths go through the entire governance stack — risk classifier,
PII redactor, semantic cache, immutable audit log, Prometheus metrics —
identically to all other providers.

**Rationale for dual-path over a single choice:** The two paths serve
different architectural requirements. Collapsing them into one would
force a trade-off between platform demonstrability and data residency.
Maintaining both makes the trade-off explicit and usage controlled.

---

## Integration design

### Hosted NIM (`ModelPreference.NVIDIA`)

- **Provider config:** `nvidia_nim_provider.py` follows the same
  `ProviderConfig` + `health_check()` pattern as all other providers.
  Health check calls `/v1/models` — a read-only, zero-token-cost
  liveness probe.
- **Model string:** LiteLLM composes
  `nvidia_nim/nvidia/nemotron-3.5-lightning-30b-a3b` from provider
  prefix and model ID. The `nvidia/` namespace prefix is part of the
  canonical model ID on the NVIDIA catalogue and is intentional.
- **Fallback chain:** NIM → Anthropic → OpenAI → Ollama, matching the
  ACCURATE tier ordering on the assumption that a caller choosing NIM
  is prioritising capability over cost.
- **Cost model:** Nemotron-3.5-lightning-30b is currently free on the
  hosted tier. `providers.yaml` records `$0.20/$0.20` per 1M tokens
  as a non-zero placeholder to avoid zeroing out cost telemetry.

### Local Nemotron-mini (`ModelPreference.NVIDIA_LOCAL`)

- **Model:** `nemotron-mini` pulled via Ollama (2.7GB, 128k context,
  zero cost).
- **Fallback chain:** local Nemotron-mini → hosted NIM → Anthropic →
  OpenAI. Fallback to hosted NIM preserves model capability and family 
  continuity if Ollama is unavailable, at the cost of losing the data 
  residency guarantee. This is an explicit, documented degradation — callers
  requiring hard data residency must handle the fallback signal in the
  response.
- **Cost model:** zero — runs locally via Ollama, same as all other
  local models in `providers.yaml`.

---

## What was deliberately not built

- **Self-hosted NIM container:** Requires an NVIDIA GPU instance for
  production-grade throughput via TensorRT-LLM or vLLM and no GPU
  instance is available in the current environment. Reversible — swap
  `api_base` in the provider config to point at a self-hosted `/v1`
  endpoint; no other code changes required.
- **30B local model:** Nemotron-3.5-lightning-30b open weights could
  be run locally via Ollama on CPU and requires ~20GB RAM and run at
  ~1–3 tokens/second on CPU-only hardware. The model can not be locally used 
  on an 8GB machine. Nemotron-mini (2.7GB) is the largest
  variant that runs without any hardware constraints.
- **Nemotron fine-tuning via NeMo:** NeMo Agent Toolkit supports
  domain specialisation of Nemotron models. This is out of scope as the gateway
  is a routing and governance layer only.
- **NVIDIA_LOCAL in AUTO routing:** Routing local Nemotron into the
  automatic preference path without explicit caller opt-in would
  introduce an uncontrolled Ollama dependency for general traffic.

---

## Consequences

**Positive:**
- Both Nemotron deployment modes are available with no additional
  infrastructure beyond Ollama which is already used
- Full governance stack applies to both paths identically — NIM and
  local Nemotron requests are audited, PII-scrubbed, risk-classified,
  and cached like OpenAI and Anthropic requests
- Data residency requirement is met by `NVIDIA_LOCAL` — completions
  never leave the host machine. The gateway's PII gate additionally
  prevents personal data reaching any external provider across all
  paths. NVIDIA_LOCAL provides a further control layer for workloads
  requiring hard localisation regardless of content.
- Integration is reversible at the config layer — self-hosted NIM
  container requires changing `api_base` only

**Negative:**
- `NVIDIA` (hosted): ~1,000ms latency floor from network RTT to
  NVIDIA US infrastructure. The gateway's PII gate prevents personal
  data reaching the hosted endpoint by design. For workloads requiring
  hard data localisation regardless of content (air-gapped, regulated
  financial data), use `NVIDIA_LOCAL` instead
- `NVIDIA_LOCAL` (local): limited to smaller Nemotron variants on
  CPU-only hardware; inference speed (~500–2,000ms) is hardware-dependent
  and not reproducible across machines
- `NVIDIA_LOCAL` falls back to hosted NIM if the NVIDIA_LOCAL fails and 
  so callers with hard residency requirements must
  monitor the `provider` field in the response and handle the
  degradation explicitly

**Production upgrade path:**
- Deploy NIM container on a GPU-enabled cloud instance co-located with the    
  gateway. Point `api_base` in `nvidia_nim_provider.py` at the self-hosted 
  endpoint
- For strict data localisation requirements: the gateway's PII gate
  prevents personal data reaching the hosted NIM endpoint by design.
  For workloads requiring hard localisation regardless of PII content,
  self-hosted NIM on EU-region infrastructure is the correct path —
  deploy NIM container on EU-region GPU instance and point `api_base`
  at the self-hosted endpoint
- Evaluate NeMo Agent Toolkit for domain fine-tuning once a production
  GPU deployment is in place
- Remove `NVIDIA_LOCAL` fallback to hosted NIM if the deployment
  context requires a hard residency guarantee with no exceptions