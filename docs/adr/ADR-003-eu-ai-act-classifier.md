# ADR-003 — EU AI Act Classifier: Keyword Heuristic over LLM-Based Classification

**Date:** 2026-07-04  
**Status:** Accepted  
**Author:** [Your name]

---

## Context

Every request must be classified into one of four EU AI Act risk tiers
before reaching an LLM provider:

| Tier | Legal basis | Gateway action |
|---|---|---|
| Unacceptable | Article 5 — Prohibited practices | 403 reject |
| High | Annex III — High-risk use cases | Allow + Article 13 header |
| Limited | Article 50 — Transparency obligations | Allow + audit |
| Minimal | Default | Allow + audit |

Three classification approaches were evaluated:

| Approach | Latency added | Cost added | Explainability |
|---|---|---|---|
| LLM-based (ask the model to classify) | +1–3s per request | ~$0.001 per call | Low — black box |
| Embedding similarity (match against tier descriptions) | +50–100ms | Zero (local) | Medium |
| Keyword/intent heuristic | <1ms | Zero | High — fully auditable |

---

## Decision

**Use an intent + topic keyword heuristic over LLM-based or
embedding-based classification.**

A request is classified at a tier only when it matches **at least one
topic signal AND at least one intent signal** from that tier's map.
Topic-only or intent-only matches do not trigger classification.

**Rationale for AND logic:** The EU AI Act classifies AI systems by
*purpose*, not subject matter alone. Asking "what is a CV?" is not High
Risk; making hiring decisions is. Intent + topic captures this
distinction more faithfully than topic-only matching, reducing false
positives on informational queries about regulated domains.

**Rationale against LLM-based classification:** Adding an LLM call to
decide whether to make an LLM call is circular, adds 1–3 seconds of
latency to every request, and costs money — directly undermining the
cost-protection objective of the gateway. A governance feature that
itself generates cost is a design contradiction.

---

## Consequences

**Positive:**
- Sub-millisecond classification adds negligible latency
- Fully auditable — every classification decision has an explicit
  matched topic and intent keyword recorded in the audit log
- Zero additional API cost
- All four tiers implemented: Unacceptable (Article 5),
  High (Annex III), Limited (Article 50), Minimal (default)
- Article 13 transparency requirement met via `X-Risk-Tier` response
  header on High Risk requests — without changing the response schema

**Negative:**
- Keyword matching is brittle — novel phrasing of prohibited
  requests may evade detection if neither topic nor intent
  keywords match
- Requires manual maintenance as the EU AI Act's implementing
  acts and guidelines evolve (expected through 2026–2027)

**Known gaps:**
- No confidence score — classification is binary (match/no match),
  not probabilistic
- English only — non-English requests are not classified accurately

**Production upgrade path:**
- Layer an embedding-based similarity check on top of the keyword
  heuristic for requests that score near the boundary
- Subscribe to EU AI Act implementing acts updates and maintain
  the keyword map accordingly