# ADR-002 — PII Detection: Detect-and-Reject over Scrub-and-Forward

**Date:** 2026-07-04  
**Status:** Accepted  
**Author:** [Your name]

---

## Context

The gateway must protect against personal data entering LLM providers
or appearing in responses. Two standard approaches exist:

| Approach | Behaviour | Risk |
|---|---|---|
| Scrub-and-forward | Replace PII with placeholders, send sanitised prompt | LLM may reconstruct PII from context; placeholders degrade response quality |
| Detect-and-reject | Block the request entirely, return 400 with entity types | Caller must clean their own data; no PII ever leaves the gateway |

The gateway also checks **responses** — a second, asymmetric scan catches
LLM hallucination or echo of personal data at egress.

---

## Decision

**Use detect-and-reject on both request (ingress) and response (egress).**

Two asymmetric entity lists are maintained:

**Request entities (broader):**
`PERSON, EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD, IBAN_CODE,
IP_ADDRESS, NRP, MEDICAL_LICENSE, URL`

**Response entities (tighter — excludes PERSON):**
`EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD, IBAN_CODE,
IP_ADDRESS, MEDICAL_LICENSE`

`PERSON` is excluded from response scanning because spaCy's NER model
produces false positives on LLM greetings (e.g. "Hi" classified as a
person name at borderline confidence). The real egress risk is structured
sensitive data, not named entities.

Score threshold: **0.70** — filters low-confidence detections without
missing genuine PII.

---

## Consequences

**Positive:**
- No PII ever reaches an LLM provider or is stored in the audit log
- Asymmetric entity lists reduce false positive rate on responses
- Rejection payload contains entity types only — never the actual PII
  value (avoids the error response itself becoming a data leak)
- Maps directly to GDPR Article 5 (data minimisation) and
  EU AI Act Article 10 (data governance for high-risk AI)

**Negative:**
- Callers must pre-sanitise their own data — adds friction for
  legitimate use cases involving names or locations
- Response-side egress block is billed (tokens already consumed)
  but no content is delivered — documented in audit log as
  `pii_blocked_at_egress`

**Known gaps:**
- English only (`language="en"`) — multilingual support requires
  `NlpEngineProvider` with additional spaCy models (de, nl)
  for German/Dutch EU deployments
- Streaming response PII check not implemented — buffering a full
  stream before yielding defeats the purpose of streaming;
  documented as a known limitation in SCALING.md
- `LOCATION` entity removed from monitored list — Presidio correctly
  identifies country names (e.g. "France") as locations, causing
  false positives on common geographic references in conversation

**Production upgrade path:**
- Add multilingual spaCy models for EU market deployment
- Implement confidence score tuning per entity type rather than
  a single global threshold