# app/services/pii_detector.py
"""
PII detection for nexus-ai-gateway using Microsoft Presidio.

Design decisions:
- Detect-and-reject, never scrub-and-forward. An enterprise gateway
  that silently redacts and proceeds is weaker governance than one
  that surfaces PII to the caller and requires them to clean it.
- Entity types only in the rejection payload — no offsets, no values,
  to avoid the error response itself becoming a data leak.
- English only (en) for now. Multilingual support (de, nl) is a
  documented gap — requires NlpEngineProvider config and heavier
  spaCy models.
- Both request and response are checked. A response check catches
  LLM hallucination or echo of personal data; it is billed (tokens
  already spent) but blocked at egress. The audit log records this
  as pii_blocked_at_egress, not a free operation.
"""

import logging
from functools import lru_cache
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

logger = logging.getLogger(__name__)

# Entity types that trigger rejection.
# Curated for enterprise/EU AI Act relevance — not every Presidio
# entity type is worth blocking on (e.g. DATE_TIME is too broad).

REQUEST_MONITORED_ENTITIES = [
    "PERSON",           # user may submit someone else's name
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "IBAN_CODE",
    "IP_ADDRESS",
    "NRP",              # Nationality, Religious, Political — EU AI Act sensitive
    "MEDICAL_LICENSE",
    "URL",
]

RESPONSE_MONITORED_ENTITIES = [
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "IBAN_CODE",
    "IP_ADDRESS",
    "MEDICAL_LICENSE",
]

@lru_cache(maxsize=1)
def _get_analyser() -> AnalyzerEngine:
    """
    Initialises Presidio with an explicit model reference —
    bypasses Presidio's auto-download logic which requires write
    access to site-packages at runtime (incompatible with non-root
    container users).
    """
    logger.info("Initialising Presidio AnalyzerEngine (one-time cold start)")
    provider = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}],
    })
    return AnalyzerEngine(nlp_engine=provider.create_engine())


# CHANGED: added optional entities parameter
def detect_pii(text: str, entities: list[str] | None = None) -> list[str]:
    """
    Analyses text for PII entities.
    Returns a deduplicated list of entity type strings found.
    Pass `entities` explicitly to use a custom list —
    defaults to REQUEST_MONITORED_ENTITIES if not specified.
    """
    if not text or not text.strip():
        return []

    analyser = _get_analyser()
    results = analyser.analyze(
        text=text,
        language="en",
        entities=entities or REQUEST_MONITORED_ENTITIES,
        score_threshold=0.7,
    )
    return list({r.entity_type for r in results})



def check_messages(messages: list[dict]) -> list[str]:
    """
    Checks all message contents in a conversation for PII.
    Returns deduplicated entity types found across all messages.
    """
    found: set[str] = set()
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            found.update(detect_pii(content, entities=REQUEST_MONITORED_ENTITIES))
    return list(found)